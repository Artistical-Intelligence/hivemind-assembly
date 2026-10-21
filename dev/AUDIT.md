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
| Medium | Project acceptance composed regions at the candidate manifest's addresses while function checks used the pinned original entries; a manifest could point a checked region at a different function, so the real original kept running yet the region counted as recovered. | Both project scopes reject region addresses that differ from the pinned check entries; Windows checks pin addresses at configuration. | `test_project_reconstruction.py::test_linux_project_rejects_address_override_of_checked_region`, `::test_windows_project_acceptance_pins_addresses_and_requires_regions` |

Also corrected during this pass: the experimental-learning worker selector had
malformed `<option>` markup, so only "Automatic" could be chosen in the dashboard.

Reviewed without findings: worker artifact reads (role `worker` cannot read
protected or restricted artifacts), `scoped()` path resolution and its callers,
argv-only job execution, linker-script symbol names (validated identifiers),
OS-keyring credential storage, MCP gateway summaries and project/program/linked
acceptance releases (IDs, difference names and function names only).

## 2026-10-21: browser automation, backups, Codespaces, dashboard HTTP

| Severity | Finding | Fix | Check |
| --- | --- | --- | --- |
| Medium | Restore accepted any relative path, so a crafted backup could plant foundation executables, private endpoint files or browser profile data. | Only snapshot-owned names (controller database, settings, Hermes databases, projects/artifacts/sources/knowledge/exports) are accepted. | `test_controller.py::test_restore_accepts_only_owned_workspace_data` |
| Medium | A failure during restore left a partly restored directory that would open as live data. | Everything restored is removed on failure; free space is checked first. | `test_controller.py::test_failed_restore_leaves_no_partial_workspace` |
| Medium | Model-authored Codespaces commands could ask git for the Codespace's credential or print token-bearing files into returned output. | No system/global git config, credential prompts or askpass; returned output is scrubbed of GitHub token formats and authorization values. A dedicated unprivileged user is not created; this is mitigation, not isolation. | `test_codespaces.py::test_remote_output_scrubs_tokens_and_disables_git_credentials` |
| Low | Backup verification had no total-size or manifest-size cap; names differing only in case overwrote each other on case-insensitive disks. | 16 GiB total and 64 MiB manifest caps; case-folded collisions rejected. | Same restore test |
| Low | A cached Codespaces job result answered probe/capability actions. | Cached results answer only run and status. | Same Codespaces test |
| Low | Codespaces output from a stale snapshot could overwrite newer edits. | Import is blocked when the project changed after the job, unless the owner confirms. | `test_codespaces.py::test_stale_cloud_output_requires_confirmation` |
| Low/Medium | Target import bypassed the workspace guard and checked the existing file outside the transaction. | Uses the same guard as other edits and rechecks inside the transaction. Imports now require a paused task. | `test_app.py` import test |
| Low | Dashboard errors echoed exception text (host paths, database errors); the token comparison was not constant-time. | Missing files report the name only; unexpected errors return a reference and are logged to `logs/dashboard-errors.log`; `hmac.compare_digest`. | `test_app.py::test_errors_do_not_echo_host_paths_or_internals` |
| Low | Request markers were matched as substrings, so one request ID that prefixes another could match the wrong turn. | Whole-token matching in Playwright filters and page scripts. | `test_native.py::test_request_markers_match_whole_tokens_only` |
| Low | Setup pages opened any configured conversation URL inside signed-in provider profiles. | HTTPS on the route's provider host only, enforced at configuration and when opening. | `test_native.py::test_setup_pages_refuse_foreign_or_credentialed_urls`, `::test_route_conversation_must_stay_on_provider_host` |
| Low | Downloads were size-checked only after copying. | The browser's temporary copy is checked and deleted when oversized before any copy; Playwright still writes that temporary file. | `test_native.py::test_failed_download_preserves_verified_file[oversized]` |

Reviewed without findings: page scripts pass values as arguments, profile names are
validated identifiers, downloads are hash-checked, send state is persisted before
the click, backup traversal/absolute paths are rejected, Codespaces imports use the
workspace install path, Host/Origin checks, static file whitelist and upload bounds.

These two passes cover the surfaces named above. Hermes internals, Ghidra/REA
upstream code and live provider behaviour were not audited.
