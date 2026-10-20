import asyncio
import pytest
from hivemind_assembly.automation.providers import conversation_url, usage_snapshot
from hivemind_assembly.automation.webmcp import NativeUI
from hivemind_assembly.core.common import Blocked


def test_conversation_id_requires_exact_provider_and_persistent_path():
    cfg = {"provider": "openai", "allowed_hosts": ["chatgpt.com"]}
    assert conversation_url(cfg, "https://chatgpt.com/c/1234-5678")
    for url in (
        "https://chatgpt.com/",
        "https://chatgpt.com/c/one?mode=wrong",
        "https://other.com/c/1",
        "https://user@chatgpt.com/c/1",
        "https://chatgpt.com/c/1#other",
    ):
        assert not conversation_url(cfg, url)


def test_allowance_requires_explicit_units_and_complete_window_labels():
    class Page:
        def __init__(self, values):
            self.values = values

        async def evaluate(self, *_):
            return self.values

    valid = [
        {"label": "Weekly remaining", "value": "18", "min": "0", "max": "100"},
        {"label": "Five-hour used", "value": "93", "min": "0", "max": "100"},
    ]
    assert asyncio.run(usage_snapshot(Page(valid), {})) == [
        {"name": "Weekly", "remaining": 18.0},
        {"name": "Five-hour", "remaining": 7.0},
    ]
    for bad in (
        [],
        [{"label": "Weekly", "value": "18", "min": "0", "max": "100"}],
        [{"label": "Weekly remaining", "value": "NaN", "min": "0", "max": "100"}],
        valid + valid,
    ):
        with pytest.raises(Blocked):
            asyncio.run(usage_snapshot(Page(bad), {}))


def test_webmcp_does_not_retry_or_call_unrecognized_tools():
    class Page:
        calls = 0

        async def evaluate(self, *_):
            self.calls += 1
            raise ConnectionError("lost acknowledgement")

    page = Page()
    with pytest.raises(Blocked):
        asyncio.run(NativeUI(page).call("delete_conversation", {}))
    assert page.calls == 0
    with pytest.raises(ConnectionError):
        asyncio.run(
            NativeUI(page).call("submit_conversation_message", {"prompt": "test"})
        )
    assert page.calls == 1
