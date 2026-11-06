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


@pytest.mark.parametrize("block,expected", [
    ({"type": "text", "text": "source\\x00binary"}, "NUL"),
    ({"type": "text", "text": "\\ud800"}, "UTF-8"),
    ({"type": "resource", "resource": {
        "mimeType": "text/plain; charset=iso-8859-1", "text": "plain",
    }}, "charset"),
    ({"type": "resource", "resource": {
        "mimeType": "text/plain", "text": "safe", "blob": "YQ==",
    }}, "non-text"),
])
def test_inline_source_read_rejects_non_utf8_binary_and_byte_overflow(
        block, expected):
    """Fake file-read blocks cannot disguise binary data as inline UTF-8."""
    # Turn escaped fixture strings into the actual bytes/codepoints under test.
    if block["type"] == "text":
        value = block["text"]
        if value == r"source\x00binary":
            block = {"type": "text", "text": "source" + chr(0) + "binary"}
        elif value == r"\ud800":
            block = {"type": "text", "text": chr(0xD800)}
    with pytest.raises(Blocked, match=expected):
        inline_github_mcp_text({"content": [block]})


def test_utf8_byte_budget_is_not_a_unicode_character_budget():
    """Multibyte source text must obey encoded-byte bounds."""
    value = {"content": [{"type": "text", "text": "é" * 8}]}
    with pytest.raises(Blocked, match="smaller line range"):
        inline_github_mcp_text(value, max_chars=15)
    assert inline_github_mcp_text(value, max_chars=16) == value
    # Binary-like embedded NUL fails even when well under the byte limit.
    with pytest.raises(Blocked, match="NUL"):
        inline_github_mcp_text({
            "content": [{"type": "resource",
                         "resource": {"mimeType": "application/json",
                                      "text": '{"text":"bad' + chr(0) + '"}'}}],
        }, max_chars=100)


@pytest.mark.parametrize(
    "revocation", ["remove-tool", "remove-project", "replace-endpoint", "delete-server"]
)
def test_external_inline_source_result_is_withheld_after_grant_revocation(
    tmp_path, monkeypatch, revocation
):
    """A formerly authorized source read cannot return after a lost MCP grant.

    The fake MCP response is ordinary inline text; a media-format rejection
    must not mask a revoked grant. Revocation happens *during* the awaited
    result, never through an actual network/server/process or model API.
    """
    import mcp

    store = Store(tmp_path)
    try:
        conn = Connections(store)
        spec = {
            "transport": "stdio", "command": "/not-executed",
            "args": [], "timeout": 5,
            "tools": ["get_file_contents"], "projects": ["granted-project"],
        }
        state = {"servers": {"scm": spec}}
        conn.settings = lambda: state
        calls = []
        original_authorize = conn.authorize

        def counted_authorize(server, tool, project):
            calls.append(("authorize", server, tool, project))
            return original_authorize(server, tool, project)

        conn.authorize = counted_authorize

        class FakeResult:
            def model_dump(self, **kwargs):
                return {"content": [{"type": "text", "text": "private source result"}]}

        class FakeClient:
            def __init__(self, target):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def call_tool(self, tool, arguments):
                calls.append(("dispatch", tool, arguments))
                if revocation == "delete-server":
                    state["servers"] = {}
                else:
                    replacement = dict(spec)
                    if revocation == "remove-tool":
                        replacement["tools"] = []
                    elif revocation == "remove-project":
                        replacement["projects"] = []
                    else:
                        replacement["command"] = "/other-never-executed"
                    state["servers"]["scm"] = replacement
                return FakeResult()

        monkeypatch.setattr(mcp, "Client", FakeClient)
        with pytest.raises(Blocked, match="connection changed"):
            asyncio.run(conn._external(
                "scm", "get_file_contents", {"path": "source.py"},
                "granted-project", None,
            ))
        assert calls == [
            ("authorize", "scm", "get_file_contents", "granted-project"),
            ("dispatch", "get_file_contents", {"path": "source.py"}),
        ]
    finally:
        store.close()


@pytest.mark.parametrize("hidden", [
    {"encoding": "base64"},
    {"encoding": "gzip"},
    {"contentEncoding": "base64"},
    {"base64": "YmluYXJ5"},
    {"base64Data": "YmluYXJ5"},
    {"downloadUrl": "https://example.invalid/source.zip"},
    {"resourceUrl": "https://example.invalid/source.zip"},
    {"attachmentUrl": "https://example.invalid/source.zip"},
])
def test_inline_embedded_resource_refuses_encoded_or_linked_secondary_payload(hidden):
    """A declared text field cannot launder an additional encoded/downloadable resource.

    The source-read bridge must validate the *entire* embedded resource before
    discarding its wrapper, not merely its mimeType and text. This is a purely
    local JSON fixture; none of the URLs are fetched or materialized.
    CHECKS PENDING / AWAITING CI: execution not claimed.
    """
    resource = {"mimeType": "text/plain; charset=utf-8", "text": "safe text"}
    resource.update(hidden)
    with pytest.raises(Blocked):
        inline_github_mcp_text({
            "content": [{"type": "resource", "resource": resource}]
        })


@pytest.mark.parametrize("descriptor", ["file", "attachment", "artifact"])
def test_nested_mcp_file_descriptors_cannot_escape_as_structured_metadata(descriptor):
    """Link-like file descriptors without type=resource_link are still unsafe.

    Keep ordinary harmless JSON metadata usable, but do not return an
    attachable file descriptor under a nonstandard structured-content key.
    """
    with pytest.raises(Blocked):
        inline_github_mcp_text({
            "content": [{"type": "text", "text": "inline source"}],
            "structuredContent": {
                "result": {
                    descriptor: {
                        "url": "https://example.invalid/private-attachment.zip",
                        "mimeType": "application/zip",
                    }
                }
            },
        })


def test_inline_mcp_safe_source_metadata_does_not_require_url_blacklisting():
    """An ordinary informational URL is not a resource/download descriptor."""
    value = {
        "content": [{"type": "text", "text": "print('ok')"}],
        "structuredContent": {
            "metadata": {"documentation_url": "https://example.invalid/docs"}
        },
    }
    assert inline_github_mcp_text(value) == value
