# GitHub MCP text-only source retrieval — avoid file materialization prompts

**Owner directive: November 5, 2026. Applicable to HA's ChatGPT Chat Mode developer and MCP workflows. CHECKS PENDING for native live external acceptance.**

## Observed permission boundary

A file read through the platform-provided **GitHub MCP** `get_file_contents` returned a GitHub MCP *embedded resource / file attachment*. ChatGPT then asked the owner: **"Allow file materialization?"** This is a separate, platform-controlled attachment gate.

The plugin's app-specific permission was independently checked and already showed **Allow all actions / Never ask**. Therefore do **not** repeatedly ask the owner to increase plugin permissions or infer that another settings update will eliminate a materialization prompt. HA cannot suppress ChatGPT's host-level security prompt or modify a third-party managed GitHub MCP server.

## Mandatory operational workaround

**For all ordinary UTF-8 repository/source/document file reads, request inline text instead of an MCP attachment:**

1. In ChatGPT with the connected GitHub tools, use the first-party `GitHub.fetch_file` tool (`mcp__GitHub__fetch_file`) for a known path and branch/ref. It returns **inline text and a blob SHA**, without a file attachment. It supports bounded `start_line`/`end_line`. Prefer those for long source files.
2. For directory inventory and GitHub API metadata, use `GitHub.fetch` (`mcp__GitHub__fetch`) with a supported GitHub REST URL; it returns JSON as plain text. Avoid calling `GitHub_MCP.get_file_contents` for file content when an inline-text tool is available. Its directory mode may not return files, but prefer the no-attachment path consistently.
3. For GitHub Actions run/job logs, use `GitHub.fetch_workflow_job_logs` (returns decoded text), not the artifact ZIP downloader merely to inspect text.
4. Never call `GitHub_MCP.get_file_contents` on a file path as an automatic fallback if a text read is rejected. Check authorization, path/ref spelling and available inline alternatives. If a file is genuinely binary or oversized, report the limitation and use an explicitly requested/authorized binary transfer workflow **only when the actual bytes are necessary**. Do not silently trigger a materialization dialog.
5. The separate hosted ChatGPT approval remains authoritative. **Never bypass it or claim it has been globally disabled.** The goal is to avoid provoking it during tasks that only need text.

## HA native MCP bridge implementation

`_app/hivemind_assembly/integrations/mcp.py` now includes `inline_github_mcp_text`, scoped to the HA outbound connection's `get_file_contents` tool **only for server names containing `github`**:

- A bounded MCP `resource` containing `text/plain` or `application/json` with a literal text field is converted into a regular `type=text` block, including any mirrored `structuredContent.content`.
- MCP `resource_link`, base64-only embedded resources, images and other non-text media are **not downloaded or materialized**. They produce a clear `Blocked` result directing the worker to an inline bounded read or a separately authorized binary workflow.
- Oversized inline content produces an explicit line-range recommendation rather than moving the file to a separate attachment.
- Other MCP tools/servers are left untouched. Secrets, permissions, provider settings, transport, session and outbound request processing retain their prior boundaries.

**Important distinction:** The HA bridge changes HA's own native MCP result handling only. It does **not** remotely update the separately installed GitHub MCP service or ChatGPT's platform attachment gate. In ChatGPT itself, the no-prompt behavior relies on selecting the already-working **inline GitHub text connector**, not on changing a provider's server.

## Acceptance

- Confirm the GitHub file read via `mcp__GitHub__fetch_file` returns text and SHA in the current session without an attachment prompt.
- Focused tests: `tests/test_mcp_inline_text.py` must pass; it checks inline embedded-resource extraction, preserved metadata, size bounding, fail-closed link/binary cases, and explicit GitHub tool scoping.
- Independent source/security review must assess both the scoped conversion and full native MCP behavior.
- Live HA external MCP connection and hosted ChatGPT plugin behavior are separate acceptance tests. We cannot guarantee **all** future tool calls avoid platform approvals, since other operations and actual binary transfers can require them.

**No RE-Wizard repository, scheduled task, permission setting or third-party GitHub MCP server was modified in this change.**
