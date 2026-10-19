import pytest
from workbench.native import parse_response, NativeBrowser
from workbench.common import ContractError, Blocked


def test_response_identity():
    assert parse_response('{"request_id":"r","type":"brief"}', "r")["type"] == "brief"
    with pytest.raises(ContractError):
        parse_response('{"request_id":"wrong","type":"brief"}', "r")


@pytest.mark.parametrize(
    "text",
    [
        "do this now",
        '{"request_id":"r","type":"shell"}',
        'explanation {"request_id":"r","type":"brief"}',
    ],
)
def test_untrusted_prose_not_tool(text):
    with pytest.raises(ContractError):
        parse_response(text, "r")


def test_code_fence():
    assert (
        parse_response('```json\n{"request_id":"r","type":"brief"}\n```', "r")["type"]
        == "brief"
    )


def test_native_host_scope():
    b = NativeBrowser(
        {"routes": {"worker.opus": {"allowed_hosts": ["claude.ai"]}}}, ".", None
    )
    b.validate_url("worker.opus", "https://claude.ai/chat/1")
    for url in [
        "https://evil.example/chat",
        "https://claude.ai.evil.example",
        "http://claude.ai/chat",
        "https://user:pass@claude.ai/chat",
    ]:
        with pytest.raises(Blocked):
            b.validate_url("worker.opus", url)


@pytest.mark.parametrize("failure", ["hash", "interrupted"])
def test_failed_download_preserves_verified_file(store, tmp_path, failure):
    import asyncio
    from pathlib import Path
    from hivemind_assembly.automation.native import NativeBrowser
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.common import ContractError

    class Download:
        async def save_as(self, path):
            Path(path).write_bytes(b"new invalid bytes")
            if failure == "interrupted":
                raise ConnectionError("interrupted transfer")

    class Info:
        @property
        def value(self):
            async def result():
                return Download()

            return result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Link:
        def filter(self, **kwargs):
            return self

        async def count(self):
            return 1

        async def click(self):
            pass

    class Page:
        def locator(self, selector):
            return Link()

        def expect_download(self):
            return Info()

    class Native(NativeBrowser):
        async def observe(self, route):
            pass

        async def page(self, route):
            return Page()

    target = tmp_path / "verified.bin"
    target.write_bytes(b"earlier verified bytes")
    with pytest.raises((ContractError, ConnectionError)):
        asyncio.run(
            Native({}, tmp_path, Controller(store)).download(
                "worker.opus", ".download", target, "0" * 64
            )
        )
    assert target.read_bytes() == b"earlier verified bytes"
    assert not list(tmp_path.glob("*.download"))
