import copy
import json

import httpx
import pytest

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.integrations.github import (
    GitHubAuth,
    GitHubClient,
    GitHubHTTP,
    GitHubError,
)


class MemoryVault:
    value = None

    def ready(self):
        pass

    def read(self):
        return copy.deepcopy(self.value)

    def write(self, value):
        self.value = copy.deepcopy(value)

    def clear(self):
        self.value = None


class AuthHTTP:
    def __init__(self):
        self.calls = []
        self.replies = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return copy.deepcopy(response)


@pytest.fixture
def auth(tmp_path):
    now = [1000.0]
    http = AuthHTTP()
    instance = GitHubAuth(
        tmp_path, http=http, vault=MemoryVault(), clock=lambda: now[0]
    )
    return instance, http, now


DEVICE = {
    "device_code": "private-device-code",
    "user_code": "ABCD-1234",
    "interval": 5,
    "expires_in": 900,
    "verification_uri": "https://github.com/login/device",
}
TOKEN = {
    "access_token": "secret-access",
    "refresh_token": "secret-refresh",
    "expires_in": 28800,
    "scope": "repo",
}
USER = {"login": "owner", "id": 123}


def connect(auth):
    a, http, now = auth
    http.replies = [DEVICE, TOKEN, USER]
    a.start("client123")
    now[0] += 5
    return a.poll()


def test_device_flow_pacing_slowdown_and_secrets(auth):
    a, http, now = auth
    http.replies = [
        DEVICE,
        {"error": "slow_down"},
        {"error": "authorization_pending"},
        TOKEN,
        USER,
    ]
    visible = a.start("client123")
    assert "device_code" not in visible
    assert http.calls[0][2]["data"]["scope"] == "repo"
    assert a.poll()["status"] == "pending" and len(http.calls) == 1
    now[0] += 5
    assert a.poll()["interval"] == 10
    assert a.poll()["status"] == "pending" and len(http.calls) == 2
    now[0] += 10
    assert a.poll()["status"] == "pending"
    now[0] += 10
    result = a.poll()
    assert (
        result["login"] == "owner" and a.vault.value["access_token"] == "secret-access"
    )
    assert "secret-" not in json.dumps([result, a.status()])
    assert "client_secret" not in http.calls[-2][2]["data"]


@pytest.mark.parametrize(
    "failure", ["access_denied", "expired_token", "incorrect_client_credentials"]
)
def test_device_errors_are_actionable_and_no_secrets_saved(auth, failure):
    a, http, now = auth
    http.replies = [DEVICE, {"error": failure, "error_description": "secret-access"}]
    a.start("client123")
    now[0] += 5
    with pytest.raises(Blocked) as error:
        a.poll()
    assert "secret-access" not in str(error.value)
    assert a.vault.value is None and a.pending is None


def test_missing_repo_scope_rejected(auth):
    a, http, now = auth
    http.replies = [DEVICE, {**TOKEN, "scope": "read:user"}]
    a.start("client123")
    now[0] += 5
    with pytest.raises(Blocked, match="repo scope"):
        a.poll()
    assert a.vault.value is None


def test_refresh_and_restart_keep_account_binding(auth, tmp_path):
    connect(auth)
    a, http, now = auth
    now[0] += 28800
    http.replies = [{**TOKEN, "access_token": "rotated"}, USER]
    restarted = GitHubAuth(tmp_path, http=http, vault=a.vault, clock=lambda: now[0])
    assert restarted.credentials()["access_token"] == "rotated"
    refresh = http.calls[-2][2]["data"]
    assert refresh["grant_type"] == "refresh_token" and "client_secret" not in refresh
    assert restarted.status()["connected"]
    assert restarted.disconnect() == {"connected": False}
    assert a.vault.value is None


def test_refresh_account_mismatch_not_saved(auth):
    connect(auth)
    a, http, now = auth
    now[0] += 28800
    http.replies = [{**TOKEN, "access_token": "wrong"}, {**USER, "id": 999}]
    with pytest.raises(Blocked, match="account changed"):
        a.credentials()
    assert a.vault.value["access_token"] == "secret-access"


def test_expiry_cancel_and_status_do_not_poll(auth):
    a, http, now = auth
    http.replies = [DEVICE]
    a.start("client123")
    with pytest.raises(Blocked, match="already pending"):
        a.start("client123")
    for _ in range(10):
        a.status()
    assert len(http.calls) == 1
    now[0] += 901
    with pytest.raises(Blocked, match="expired"):
        a.poll()
    a.cancel()
    assert a.pending is None


def test_client_pins_identity_for_operation_and_uses_private_empty_create(auth):
    connect(auth)
    a, http, now = auth
    client = GitHubClient(a)
    http.replies = [USER, GitHubError(404), {"id": 42}, {}]
    client.identity()
    assert client.lookup("owner", "repo") is None
    # Reconnection elsewhere cannot silently change the operation's account.
    a.vault.value["access_token"] = "different-account-token"
    client.create("owner", "repo", "description")
    client.describe("owner", "repo", "clean")
    creation = http.calls[-2]
    assert creation[:2] == ("POST", "/user/repos")
    assert creation[2]["token"] == "secret-access"
    assert creation[2]["data"]["private"] is True
    assert creation[2]["data"]["auto_init"] is False


def test_http_denial_redirect_and_secret_redaction(monkeypatch):
    calls = []
    statuses = iter([403, 302, 500])

    def handler(request):
        calls.append(request)
        return httpx.Response(
            next(statuses),
            json={"message": "secret-access"},
            headers={"location": "https://other.example"},
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    api = GitHubHTTP()
    for status in (403, 302, 500):
        with pytest.raises(GitHubError) as error:
            api.request(
                "POST", "/user/repos", token="secret-access", data={"private": True}
            )
        assert error.value.status == status and "secret-access" not in str(error.value)
    assert len(calls) == 3  # No retries or redirects for a write.


@pytest.mark.parametrize("status", [202, 204])
def test_http_empty_success_is_not_misclassified_as_unknown_write(monkeypatch, status):
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda req: httpx.Response(status)), **kw
        ),
    )
    assert (
        GitHubHTTP().request(
            "POST",
            "/repos/owner/repo/actions/workflows/native-tests.yml/dispatches",
            token="private",
            data={},
        )
        == {}
    )
