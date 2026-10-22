"""Permanent address: free-plan-only deployment, saved identity, relay and approval codes."""

import json

import pytest

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.integrations import chrome_helper
from hivemind_assembly.integrations.permanent import Permanent, Relay, assert_free_subscriptions

ACCOUNT = "0123456789abcdef0123456789abcdef"


class Vault:
    def __init__(self):
        self.value = None

    def read(self):
        return self.value

    def write(self, value):
        self.value = value


class FakeCloudflare:
    def __init__(self, subscriptions=(), subdomain=None, accounts=None, existing=None):
        self.calls = []
        self.subscriptions = list(subscriptions)
        self.subdomain = subdomain
        self.accounts = accounts or [{"id": ACCOUNT, "name": "Mine"}]
        self.existing = existing

    def __call__(self, token):
        assert token == "tok"
        return self

    def call(self, method, path, payload=None, raw=None, content_type=None, allow_missing=False):
        self.calls.append((method, path, payload, raw))
        if path.startswith("/accounts?"):
            return self.accounts
        if path.endswith("/subscriptions"):
            return self.subscriptions
        if path.endswith("/workers/subdomain"):
            if method == "PUT":
                self.subdomain = payload["subdomain"]
                return {}
            return {"subdomain": self.subdomain} if self.subdomain else None
        if path.endswith("/settings"):
            return self.existing
        return {}


def permanent(tmp_path, cf):
    return Permanent(tmp_path, lambda: None, vault=Vault(), api_factory=cf)


def test_deploys_once_on_workers_free_and_keeps_its_identity(tmp_path, monkeypatch):
    cf = FakeCloudflare()
    p = permanent(tmp_path, cf)
    monkeypatch.setattr(p, "start", lambda: None)
    result = p.deploy("tok", confirmed_free=True)
    settings = p.settings()
    assert result["origin"] == settings["origin"] and settings["enabled"]
    assert settings["origin"].startswith("https://ha-connection-") and settings["origin"].endswith(".workers.dev")
    upload = next(c for c in cf.calls if c[0] == "PUT" and "/workers/scripts/" in c[1])
    metadata = json.loads(upload[3].split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
    bindings = {b["name"]: b for b in metadata["bindings"]}
    assert bindings["DEVICE_KEY"]["text"] == p.vault.value["device_key"]
    assert bindings["PUBLIC_ORIGIN"]["text"] == settings["origin"]
    assert metadata["migrations"]["new_sqlite_classes"] == ["HaBridge"]
    # A second run reuses the same Worker and key instead of creating another.
    cf.existing = {"tags": ["ha-permanent-connection"]}
    assert p.deploy("tok", confirmed_free=True)["origin"] == settings["origin"]
    assert p.vault.value["device_key"] == bindings["DEVICE_KEY"]["text"]


def test_refuses_paid_plans_unconfirmed_setup_and_foreign_workers(tmp_path):
    with pytest.raises(Blocked, match="paid"):
        assert_free_subscriptions([{"product": "Workers Paid", "price": 5, "state": "active"}])
    assert_free_subscriptions([{"product": "Workers Free", "price": 0}, {"product": "Domains", "price": 9}])
    with pytest.raises(Exception, match="free Workers|Workers Free"):
        permanent(tmp_path, FakeCloudflare()).deploy("tok", confirmed_free=False)
    with pytest.raises(Blocked, match="isn't HA's"):
        permanent(tmp_path, FakeCloudflare(subdomain="me", existing={"tags": ["other"]})).deploy("tok", confirmed_free=True)
    with pytest.raises(Blocked, match="several"):
        permanent(tmp_path, FakeCloudflare(accounts=[{"id": ACCOUNT}, {"id": "f" * 32}])).deploy("tok", confirmed_free=True)


def test_approval_codes_go_through_the_worker(tmp_path, monkeypatch):
    p = permanent(tmp_path, FakeCloudflare())
    p.save(origin="https://ha-connection-0123456789ab.me.workers.dev", enabled=True)
    sent = []
    monkeypatch.setattr(p, "request", lambda path, data=None: sent.append((path, data)) or {"expires_in": 600, "flow_verified": True})
    general = p.pairing()
    assert sent[-1] == ("/device/pair", {"code": general["code"]})
    callback = "https://claude.ai/api/mcp/auth_callback"
    page = p.settings()["origin"] + "/authorize?client_id=c1&redirect_uri=" + callback
    monkeypatch.setattr(p, "status", lambda: {"state": "ready", "endpoint": p.settings()["origin"] + "/mcp"})
    bound = chrome_helper.pair(p, "Claude", page, "f" * 24)
    assert sent[-1][1] == {"code": bound["pairing_code"], "flow": "f" * 24, "client_id": "c1", "redirect_uri": callback}


class Socket:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(json.loads(text))


def test_relay_answers_in_parts_and_never_replays(tmp_path):
    handled = []

    class Rpc:
        def handle(self, message):
            handled.append(message)
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"text": "x" * 130000}}

    relay = Relay("https://ha-connection-0123456789ab.me.workers.dev", "key", Rpc())
    relay.ws = Socket()
    relay.received(json.dumps({"id": "r1", "message": {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}}))
    relay.pool.shutdown(wait=True)
    parts = relay.ws.sent
    assert len(parts) == 3 and all(p["id"] == "r1" and p["total"] == 3 for p in parts)
    assert json.loads("".join(p["text"] for p in parts))["result"]["text"] == "x" * 130000
    assert len(handled) == 1
