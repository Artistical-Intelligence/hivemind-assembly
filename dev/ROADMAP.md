# Hivemind Assembly roadmap

Current version: 0.31.0. This roadmap lists only work that is still open; what is
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

## Planned for later: the owner's knowledge collection

The owner's 1000+ page collection of information, currently one Word document,
becomes OKF-style Markdown files: one file per topic in folders by category, each
starting with a short header (title, type, tags, other names), with links between
files and an index page per folder. Tag filtering then works per topic instead of
per document.

1. Owner: create a private repository at github.com/new (for example
   `ha-knowledge`), choose Private, then Create.
2. AI assistant: convert the Word document into those files, one per heading.
   Tables stay tables and pictures become separate image files. Put the files in
   the repository.
3. HA changes:
   - import a whole folder, taking tags from each file's header;
   - split files at headings;
   - replace the previous copy on re-import instead of adding a second one
     (today every import adds a new source);
   - stop pictures and tables in Word files from causing problems (today any
     picture marks the whole document as incompletely read, which blocks tasks
     that rely on it, and table cells arrive as separate paragraphs);
   - add ranked search (SQLite FTS5 instead of the current word-count scan), name
     lookup from titles and other names, and AI search tools (search, open a
     section, follow links), all within the task's selected tags. Add semantic
     (vector) search only if tests with real questions show it is needed.

## Verification

### Current evidence

<!-- status:begin -->
<!-- Generated by dev/status_docs.py from _app/release_status.json; edit that file. -->

**Version 0.31.0.** Live native routes accepted: 0 of 5. Unattended worker/adviser/Ghidra loop with live models: not established. Clean Windows desktop installation: not verified.

| Evidence | Commit | Runs | Host | Model inference |
| --- | --- | --- | --- | --- |
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
<!-- status:end -->

Detailed current and historical evidence is retained in
[`release_status.json`](../_app/release_status.json). Runtime boundaries and setup
instructions are in [README](../README.md); architectural decisions and external
approaches are in [ARCHITECTURE](ARCHITECTURE.md) and
[RELATED_WORK](RELATED_WORK.md).
