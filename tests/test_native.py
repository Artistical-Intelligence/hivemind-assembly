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


@pytest.mark.parametrize("failure", ["hash", "interrupted", "oversized"])
def test_failed_download_preserves_verified_file(store, tmp_path, failure):
    import asyncio
    from pathlib import Path
    from hivemind_assembly.automation.native import NativeBrowser
    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.core.common import ContractError

    deleted = []

    class Download:
        async def path(self):
            temporary = tmp_path / "browser-temp"
            with temporary.open("wb") as handle:
                handle.truncate(33_000_000 if failure == "oversized" else 17)
            return temporary

        async def delete(self):
            deleted.append(True)

        async def save_as(self, path):
            assert failure != "oversized", "oversized downloads are never copied"
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
    from hivemind_assembly.core.common import Blocked

    with pytest.raises((ContractError, ConnectionError, Blocked)):
        asyncio.run(
            Native({}, tmp_path, Controller(store)).download(
                "worker.opus", ".download", target, "0" * 64
            )
        )
    assert target.read_bytes() == b"earlier verified bytes"
    assert not list(tmp_path.glob("*.download"))
    assert bool(deleted) == (failure == "oversized")


def test_request_markers_match_whole_tokens_only():
    from hivemind_assembly.automation.native import marker_pattern

    pattern = marker_pattern("WORKBENCH_REQUEST:abc_session")
    assert pattern.search("WORKBENCH_REQUEST:abc_session\n{...}")
    assert pattern.search("prefix WORKBENCH_REQUEST:abc_session {...}")
    assert not pattern.search("WORKBENCH_REQUEST:abc_session2\n{...}")


def test_setup_pages_refuse_foreign_or_credentialed_urls(tmp_path, store):
    import asyncio

    from hivemind_assembly.automation.native import NativeBrowser
    from hivemind_assembly.core.controller import Controller

    browser = NativeBrowser({}, tmp_path, Controller(store))
    for url in ("http://chatgpt.com/", "https://evil.example/", "https://u:p@chatgpt.com/"):
        with pytest.raises(Blocked):
            asyncio.run(browser.service_page("profile", url, ["chatgpt.com"]))


def test_route_conversation_must_stay_on_provider_host():
    import json
    from pathlib import Path

    from hivemind_assembly.automation.policy import validate_config
    from hivemind_assembly.core.common import ContractError

    config = json.loads((Path(__file__).parents[1] / "_app/config/default.json").read_text())
    route = next(iter(config["routes"].values()))
    route["conversation_url"] = "https://attacker.example/c/1"
    with pytest.raises(ContractError, match="provider host"):
        validate_config(config)
