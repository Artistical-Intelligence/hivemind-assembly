"""GitHub MCP inline-text policy contracts: no file materialization.

These tests use only local JSON-shaped MCP responses. They do not call the
external GitHub MCP, download files, change app permissions or use model APIs.
"""

from pathlib import Path

import pytest

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.integrations.mcp import inline_github_mcp_text


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


def test_mcp_bridge_normalization_only_targets_github_get_file_contents():
    source = (Path(__file__).resolve().parents[1] /
              "_app/hivemind_assembly/integrations/mcp.py").read_text()
    assert 'if tool == "get_file_contents" and "github" in server.lower():' in source
    assert "value = inline_github_mcp_text(value)" in source
    assert "await client.call_tool(tool, arguments or {})" in source
