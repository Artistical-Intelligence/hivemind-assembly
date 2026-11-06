"""Offline browser-operation receipt regressions (no live provider or browser).

An action may be a non-idempotent click. Silently pruning a completed receipt
must not let an old operation ID dispatch again, including after restart.
"""
import asyncio

import pytest

from hivemind_assembly.automation.browser_actions import (
    BrowserActions,
    MAX_RETAINED_RECEIPTS,
)
from hivemind_assembly.core.common import Blocked, Conflict, digest


class _NotARealBrowser:
    config = {"routes": {}}


def _completed(request, outcome="dispatched"):
    return {
        "hash": digest(request),
        "state": "completed",
        "result": {"ok": True, "items": [{"outcome": outcome}]},
    }


def _request(operation_id):
    return {
        "action": "click",
        "operation_id": operation_id,
        "session": "closed-browser-session",
        "snapshot": "expired-snapshot",
        "ref": "1",
    }


def test_completed_click_fence_survives_many_newer_receipts_and_restart(tmp_path):
    first = _request("click-original-0001")
    actions = BrowserActions(_NotARealBrowser(), tmp_path)
    actions.receipts[first["operation_id"]] = _completed(first)

    # Exceeds the former newest-200 auto-prune. Do not dispatch a browser.
    for i in range(225):
        request = _request(f"click-later-{i:05d}")
        actions.receipts[request["operation_id"]] = _completed(request)
    actions.save()

    restored = BrowserActions(_NotARealBrowser(), tmp_path)
    assert restored.status()["state"] == "ready"
    assert len(restored.receipts) == 226
    calls = []

    async def forbidden_dispatch(request):
        calls.append(request)
        raise AssertionError("replayed click reached the browser")

    restored._run = forbidden_dispatch
    assert asyncio.run(restored.run(first)) == restored.receipts[first["operation_id"]]["result"]
    assert calls == []
    with pytest.raises(Conflict):
        asyncio.run(restored.run({**first, "ref": "2"}))
    assert calls == []


def test_full_receipt_inventory_fails_closed_without_eviction_or_dispatch(tmp_path):
    actions = BrowserActions(_NotARealBrowser(), tmp_path)
    for i in range(MAX_RETAINED_RECEIPTS):
        request = _request(f"full-click-{i:05d}")
        actions.receipts[request["operation_id"]] = _completed(request)
    actions.save()
    previous = actions.path.read_bytes()
    restored = BrowserActions(_NotARealBrowser(), tmp_path)
    assert restored.status()["state"] == "reconciliation_required"
    assert not restored.status()["available"]
    calls = []

    async def forbidden_dispatch(request):
        calls.append(request)
        raise AssertionError("browser action dispatched past retained capacity")

    restored._run = forbidden_dispatch
    with pytest.raises(Blocked, match="owner-guided reconciliation"):
        asyncio.run(restored.run(_request("fresh-click-0001")))
    assert calls == []
    assert restored.path.read_bytes() == previous
    assert len(restored.receipts) == MAX_RETAINED_RECEIPTS

    # Previously fenced IDs must still replay without reaching the browser.
    old = _request("full-click-00000")
    assert asyncio.run(restored.run(old)) == restored.receipts[old["operation_id"]]["result"]
    assert calls == []


def test_uncertain_receipt_is_not_aged_out_by_completed_operations(tmp_path):
    actions = BrowserActions(_NotARealBrowser(), tmp_path)
    uncertain = _request("uncertain-click-001")
    actions.receipts[uncertain["operation_id"]] = {
        "hash": digest(uncertain), "state": "uncertain"
    }
    for i in range(210):
        request = _request(f"later-uncertain-{i:05d}")
        actions.receipts[request["operation_id"]] = _completed(request)
    actions.save()
    restored = BrowserActions(_NotARealBrowser(), tmp_path)
    assert uncertain["operation_id"] in restored.receipts
    calls = []

    async def forbidden_dispatch(request):
        calls.append(request)
        raise AssertionError("uncertain request was repeated")

    restored._run = forbidden_dispatch
    response = asyncio.run(restored.run(uncertain))
    assert not response["ok"]
    assert response["error"]["code"] == "UNCERTAIN"
    assert calls == []



def test_cached_open_receipt_requires_live_original_session_even_after_restart(tmp_path):
    request = {
        "action": "open",
        "operation_id": "open-browser-0001",
        "profile": "fixture",
        "url": "https://example.invalid/setup",
    }
    actions = BrowserActions(_NotARealBrowser(), tmp_path)
    receipt = _completed(request, outcome="opened")
    receipt["result"]["items"][0]["session"] = "session-already-opened"
    actions.receipts[request["operation_id"]] = receipt

    class Page:
        closed = False

        def is_closed(self):
            return self.closed

    page = Page()
    actions.sessions["session-already-opened"] = {"page": page}
    dispatched = []

    async def forbidden_dispatch(data):
        dispatched.append(data)
        raise AssertionError("an old open operation reached the browser")

    actions._run = forbidden_dispatch
    assert asyncio.run(actions.run(request)) == receipt["result"]
    page.closed = True
    closed = asyncio.run(actions.run(request))
    assert closed["ok"] is False
    assert closed["error"]["code"] == "NEED_ATTENTION"
    assert dispatched == []

    actions.save()
    restored = BrowserActions(_NotARealBrowser(), tmp_path)
    restored._run = forbidden_dispatch
    restarted = asyncio.run(restored.run(request))
    assert restarted["ok"] is False
    assert restarted["error"]["code"] == "NEED_ATTENTION"
    assert dispatched == []
