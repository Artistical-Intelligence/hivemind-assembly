# Checks status

Unified HA implementation is in progress. Missing markers alone do not prove approval; compare current files with retained check evidence. Live-provider and Windows acceptance remain distinct from source approval.

The owner has explicitly requested `v0.38.0-beta.1` for download and testing, noting that HA is still in beta. This is a narrowly scoped testing-prerelease authorization, not independent source approval. The stable release workflow and all unresolved review markers remain in force for stable publication. See `dev/beta_release_request.json` for the tested payload identity and open beta checks.

The owner additionally requested a single downloading/verifying/caching setup executable, retaining the offline alternative. `dev/online_installer_request.json` pins the existing beta's exact offline assets. This packaging-only beta addition must pass compiled failure/recovery and actual Windows installer acceptance before publication; it does not alter runtime bytes or remove review requirements.

| Item | Folder | Waiting for |
| --- | --- | --- |
| app.py | _app/hivemind_assembly/application | 2026-11-01 browser/MCP repair: independent review and regressions |
| test_debug_mcp.py | tests | 2026-11-01 browser/MCP repair: independent review and regressions |
| mcp.py | _app/hivemind_assembly/integrations | 2026-11-01 browser/MCP repair: independent review and regressions |
| debug_mcp.py | _app/hivemind_assembly/integrations | 2026-11-01 browser/MCP repair: independent review and regressions |
| auto_reconnect.py | _app/hivemind_assembly/integrations | 2026-11-01 browser/MCP repair: independent review and regressions |
| onboarding.py | _app/hivemind_assembly/automation | 2026-11-01 browser/MCP repair: independent review and regressions |
| sessions.py | _app/hivemind_assembly/automation | 2026-11-01 browser/MCP repair: independent review and regressions |
| native.py | _app/hivemind_assembly/automation | 2026-11-01 browser/MCP repair: independent review and regressions |
| online_installer.iss; build_online_installer.py; verify_online_installer.py; online_installer_request.json; ONLINE_INSTALLER.md | dev | Independent source review; compiled Windows acceptance required for this owner-authorized beta packaging addition |
| online-installer.yml | .github/workflows | Independent workflow review; preserve existing beta/stable asset bytes and identity |
| test_online_installer.py | tests | Independent test review; unit contracts are not compiled installer acceptance |
| Unified setup, automation, remote access and packaged foundations | root, application, automation, integrations, dev, tests | Independent source review and separate live acceptance; no stable release approved |
| package_beta.py; beta_release_request.json | dev | Independent packaging review; owner-authorized beta only, with required retained-payload and installed-Windows checks |
| beta-release.yml | .github/workflows | Independent workflow review; publication is prerelease-only and cannot replace stable assets |
| test_beta_packaging.py; test_integration_document_scope.py | tests | Independent source review; cross-platform archive and exact-byte fixtures are tested in the beta build |

Workflow/context source, evidence and fixture approval: [2026-10-29 independent review](checks/2026-10-29-workflow-context-review.md).

Native recovery source, focused browser fixtures and evidence documents: [2026-10-29 independent review](checks/2026-10-29-native-recovery-review.md). The report records broader baseline browser failures and live-provider limitations.

[Commit provenance](checks/2026-10-29-native-recovery-commit-map.json) maps the original local review SHAs to their GitHub imports. Every imported file tree matched the original exactly.

Sign-in observation, setup retry, automated HA MCP entry point and 0.37.1 evidence: [independent review](checks/2026-10-29-signin-mcp-review.md). The report records exact file hashes, completed checks, the blocked broader run, and live-provider limitations.

Inherited runtime guidance and provenance records: [independent review](checks/2026-10-29-runtime-provenance-review.md), with acquisition-byte and live-Windows limitations.

Setup conversation recovery, durable quota handling and 0.37.2 evidence: [independent review](checks/2026-10-29-setup-recovery-review.md). Local fixtures do not establish live-provider acceptance.

Dedicated owner MCP debugging and 0.37.3 evidence: [independent review](checks/2026-10-29-debug-mcp-review.md). Local fixtures do not establish live-provider or remote-tunnel acceptance.

Trusted connector-menu navigation and 0.37.4 evidence: [independent review](checks/2026-10-29-connector-navigation-review.md). Original live-user root cause and live provider acceptance remain unverified.

Bounded recovery, progress and target-reset restoration: [independent review](checks/2026-10-29-setup-progress-review.md). Live-provider acceptance remains unverified.

Owner-enabled MCP screenshots and OCR: [independent review](checks/2026-10-29-debug-vision-review.md). Live-provider acceptance remains unverified.
