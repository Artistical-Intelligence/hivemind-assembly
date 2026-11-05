"""GitHub MCP inline-text policy contracts: no file materialization.

These tests use only local JSON-shaped MCP responses. They do not call the
external GitHub MCP, download files, change app permissions or use model APIs.
"""

import asyncio
from pathlib import Path

import pytest

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.core.store import Store
from hivemind_assembly.integrations.mcp import (
    Connections, inline_github_mcp_text, inline_source_read_tool,
)


def test_small_embedded_text_file_becomes_plain_inline_text():
    original = {
        "content": [
            {"type": "text", "text": "successfully downloaded text file"},
            {"type": "resource", "resource": {
                "uri": "repo://owner/repo/sha/abc/path/source.py",
                "mimeType": "text/plain; charset=utf-8",
                "text": "def main():\n    return 1\n",
            }},
        ],
        "isError": False,
    }
    processed = inline_github_mcp_text(original)
    assert processed["content"] == [
        {"type": "text", "text": "successfully downloaded text file"},
        {"type": "text", "text": "def main():\n    return 1\n"},
    ]
    assert not any(block["type"] == "resource" for block in processed["content"])
    assert original["content"][1]["type"] == "resource"  # input immutable


def test_structured_resource_mirror_does_not_keep_file_attachment():
    block = {"type": "resource", "resource": {
        "mimeType": "application/json",
        "text": '{"ok":true}',
        "uri": "repo://somepath",
    }}
    result = inline_github_mcp_text({
        "content": [block], "structuredContent": {"content": [block], "status": "ok"},
    })
    assert result["content"] == [{"type": "text", "text": '{"ok":true}'}]
    assert result["structuredContent"]["content"] == result["content"]
    assert result["structuredContent"]["status"] == "ok"
    assert "repo://" not in str(result)


def test_resource_link_binary_base64_and_images_fail_closed():
    examples = [
        {"type": "resource_link", "uri": "repo://private/binary.dat", "name": "raw"},
        {"type": "resource", "resource": {"mimeType": "application/octet-stream",
                                         "blob": "YQ=="}},
        {"type": "resource", "resource": {"mimeType": "text/plain",
                                         "blob": "YQ=="}},
        {"type": "image", "data": "YQ==", "mimeType": "image/png"},
    ]
    for item in examples:
        with pytest.raises(Blocked):
            inline_github_mcp_text({"content": [item]})


def test_large_sources_request_bounded_lines_instead_of_download():
    with pytest.raises(Blocked, match="smaller line range"):
        inline_github_mcp_text({
            "content": [{"type": "text", "text": "x" * 500}]
        }, max_chars=100)


def test_invalid_metadata_is_not_silently_accepted():
    for value in (None, "text", {}, []):
        if value == {}:
            assert inline_github_mcp_text(value) == value
        else:
            with pytest.raises(ContractError):
                inline_github_mcp_text(value)
    with pytest.raises(ContractError):
        inline_github_mcp_text({"content": [{"type": "text", "text": 123}]})


def test_normal_inline_text_preserves_existing_mcp_result():
    value = {"content": [{"type": "text", "text": '{"sum":5}'}], "isError": False}
    assert inline_github_mcp_text(value) == value


def test_source_read_selection_is_independent_of_server_alias():
    # GitHub server display names are user-controlled and not identities.
    for name in ("get_file_contents", "get_file_content", "fetch_file",
                 "read_file", "read_text_file", "read_repository_file"):
        assert inline_source_read_tool(name)
    for name in ("create_file", "upload_file", "delete_file",
                 "list_tools", "get_issue", None, 123):
        assert not inline_source_read_tool(name)

    # Guard the actual outbound result-processing seam, not obsolete spelling
    # of a previous GitHub-name-specific conditional.
    source = (Path(__file__).resolve().parents[1] /
              "_app/hivemind_assembly/integrations/mcp.py").read_text()
    assert "if inline_source_read_tool(tool):" in source
    assert "value = inline_github_mcp_text(value)" in source
    assert "await client.call_tool(tool, arguments or {})" in source


@pytest.mark.parametrize("alias", ["github", "scm", "source-control"])
@pytest.mark.parametrize("result_kind", ["inline", "linked", "binary", "nested"])
def test_external_source_read_never_returns_attachment_for_alias(
        tmp_path, monkeypatch, alias, result_kind):
    # Exercise Connections._external via an in-process MCP client stub.
    # It never starts a subprocess, external server, model, or API call.
    import mcp

    store = Store(tmp_path)
    try:
        conn = Connections(store)
        conn.settings = lambda: {"servers": {
            alias: {"transport": "stdio", "command": "/not-executed",
                    "args": [], "timeout": 5},
        }}
        calls = []
        conn.authorize = lambda server, tool, project: calls.append(
            (server, tool, project))
        text = {"type": "resource", "resource": {
            "mimeType": "text/plain", "text": "safe source body"}}
        link = {"type": "resource_link",
                "uri": "repo://source/attachment", "name": "attachment"}
        binary = {"type": "resource", "resource": {
            "mimeType": "application/octet-stream", "blob": "YQ=="}}
        payloads = {
            "inline": {"content": [text]},
            "linked": {"content": [link]},
            "binary": {"content": [binary]},
            "nested": {"content": [{"type": "text", "text": "ordinary"}],
                       "structuredContent": {"extra": {"content": [link]}}},
        }

        class FakeResult:
            def model_dump(self, **kwargs):
                return payloads[result_kind]

        class FakeMCPClient:
            def __init__(self, target):
                self.target = target

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def call_tool(self, tool, arguments):
                assert tool == "get_file_contents"
                assert arguments == {"path": "source.py"}
                return FakeResult()

        monkeypatch.setattr(mcp, "Client", FakeMCPClient)
        project_id = "project-fixture-only"
        async def call():
            return await conn._external(
                alias, "get_file_contents", {"path": "source.py"},
                project_id, None,
            )
        if result_kind == "inline":
            result = asyncio.run(call())
            assert result["content"] == [
                {"type": "text", "text": "safe source body"}]
            assert "resource" not in str(result)
        else:
            with pytest.raises(Blocked):
                asyncio.run(call())
        assert calls == [(alias, "get_file_contents", project_id)]
    finally:
        store.close()
