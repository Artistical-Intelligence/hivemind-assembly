# Hivemind Assembly development

- Reverse engineering capability is the primary goal. Preserve complete Ghidra
  and REA foundations and deep, efficient integration; additions must not reduce
  upstream functionality.
- Ship one integrated application with clear internal modules. Keep core,
  automation and learning independent of the reverse engineering domain and UI.
  Do not prioritize a universal plugin system or a Codex port.
- Hermes is the initial agent runtime. The controller owns deterministic state
  and execution safeguards, not a competing general-purpose reasoning runtime.
- Native autonomous sessions are mandatory. Preserve exact configured
  provider/surface/model/mode/effort and allowance distinctions. No model API
  fallback, manual relay substitute or overage. During work, re-read usage every
  10 minutes while an account has usage left; once it runs out, check once a day.
- Learning includes knowledge, procedures and executable workflows. Measure
  correctness and speed with independent holdouts/regressions before promotion.
  Do not claim self-improvement from retrieval or contracts alone.
- Retain operation idempotency, uncertain-write reconciliation, writer epochs,
  revision fences and role isolation. Preserve originals and protected evaluators.
- Use `_app/hivemind_assembly` for implementation. `workbench` is compatibility
  only. See `dev/ARCHITECTURE.md` and `dev/ROADMAP.md`.
- Preserve user settings, histories, projects and profiles across drop-in ZIP
  updates. Runtime release root: README and launcher; internals under `_app`.
- Keep runtime data, browser profiles, credentials and private source documents
  out of version control and release artifacts.
- State what was actually verified. Keep historical evidence separate from
  current-run results; never count fixtures as live provider acceptance.

- Commit and push to `main` immediately after any file is planned and after every individual file edit, even
  several times within a single reply. Never batch changes or wait for
  checkpoints or the end of a reply. Preserve remote changes; never force-push.
  Exclude credentials, private runtime data and source material without sharing
  permission.

- Record verified evidence in `_app/release_status.json` (`evidence`, with full
  commit SHAs and run IDs), then run `python dev/status_docs.py --write`; the README
  and ROADMAP status blocks are generated and checked by tests.

<!-- checks-workflow:start (kept up to date by Hivemind Assembly) -->
## Push early, check later

Every assistant working in this repository (Claude, ChatGPT or any other) follows these rules:

1. Commit and push every file you create or change right away, before any review.
2. Mark what isn't checked yet: add a line `CHECKS PENDING: <file> — <what still needs checking>`
   to STATUS.md in the file's folder, and a row to CHECKS_STATUS.md at the top of the repository
   (item, folder, waiting for). Missing markers alone do not prove a file was checked.
3. A check is done by a different assistant session than the one that wrote the file (another
   provider when possible, otherwise a fresh conversation). The checker gets only the files and
   their sources, and writes a report under checks/ that stays in the repository.
4. When a check passes, remove its STATUS.md line (and STATUS.md once it's empty) and its
   CHECKS_STATUS.md row in the same commit as the report. When a check fails or stops early,
   keep the marker and say in STATUS.md what failed or what is left.
5. Never put anything with a pending marker into a release, the main deliverable or any other
   published output.
6. When you pick up this repository, reconcile CHECKS_STATUS.md and QUEUE.md with current files,
   their hashes and check reports: finish pending checks before starting more work. Preserve
   completed work; a changed file must be checked again. Failed checks permit focused repairs.
7. Give each worker explicit output ownership. HA's project writer lease and broker own edits
   and saves; assistants outside HA must likewise use one integration/saving owner. Save drafts
   immediately with pending markers; never wait for an entire batch or acceptance check.
8. Brief each worker with the current task, source/revision references, necessary dependencies,
   edit scope and completion criteria. Retrieve additional evidence as needed; do not replace
   required reading with a summary or repeat unrelated conversation history.
9. Validate the combined deliverable against its existing whole-project checks before completion;
   passing child tasks alone is insufficient. Reuse required checks without duplicate reviews.
10. Do not add operational performance records for these practices. Existing correctness evidence,
    recovery journals and learning evaluations remain required.
<!-- checks-workflow:end -->
