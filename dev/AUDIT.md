# Audit log

Findings are recorded with severity, the fix and the regression check. An audit
covers the named surfaces only; it is not a claim that the whole product is
free of defects.

## 2026-10-21: protected evidence, paths, commands, credentials, learning

Read-only review of protected artifacts, path scoping, command construction,
credential handling and learning promotion, followed by fixes.

| Severity | Finding | Fix | Check |
| --- | --- | --- | --- |
| High | `x86_64_c_functions` acceptance copied up to eight failing sealed cases (inputs and original outputs) into the worker-visible acceptance result, its `task` artifact and the next worker prompt. A worker could special-case them. | Full comparison stored as a `protected` artifact; workers see pass/fail, counts and the artifact ID only. | `test_reconstruction.py::test_protected_compiled_acceptance_does_not_trust_worker_checks` fails on the previous code. |
| Medium | Identifiers could begin with `-`; a worker-supplied Ghidra program name such as `-deleteProject` follows `-process` and is read as an option. | Identifiers must start with a letter, digit or underscore (also excludes `.`/`..`). | `test_architecture.py::test_identifiers_cannot_become_tool_options_or_hidden_paths` |
| Medium | Lesson promotion trusted a caller-passed `role="evaluator"` string and accepted evaluations built from caller-supplied results. | Promotion requires a host-run evaluation over a protected suite with retained samples; caller-supplied evaluations are advisory. | `test_playbook.py::test_caller_supplied_results_cannot_promote`, `test_knowledge.py::test_learning_promotion_and_rollback` |
| Low | A worker-triggered workflow promotion could use any protected artifact as its suite. | Executable assets bind to their first measured suite; later candidates must use it. | `test_workflow_learning.py::test_promotion_cannot_switch_to_another_protected_suite` |
| Low | REA failures put the absolute host path in worker-visible errors and traces. | Errors name the saved file only. | Covered by existing REA bridge tests. |
| Low | MCP bearer redaction replaced only the exact token; encoded echoes and raw HTTP transport exceptions could reach results and traces. | Redaction covers URL, base64 (standard/url-safe, padded or not) and hex forms; non-contract HTTP errors are reduced to the exception type. | `test_mcp_connections.py::test_bearer_redaction_covers_encoded_echoes` |

Also corrected during this pass: the experimental-learning worker selector had
malformed `<option>` markup, so only "Automatic" could be chosen in the dashboard.

Reviewed without findings: worker artifact reads (role `worker` cannot read
protected or restricted artifacts), `scoped()` path resolution and its callers,
argv-only job execution, linker-script symbol names (validated identifiers),
OS-keyring credential storage, MCP gateway summaries and project/program/linked
acceptance releases (IDs, difference names and function names only).

Not yet audited: native browser session automation, backup/restore archives,
Codespaces job import and the dashboard's HTTP surface beyond token checks.
