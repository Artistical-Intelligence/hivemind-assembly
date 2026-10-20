import asyncio
from types import SimpleNamespace
import pytest
from hivemind_assembly.integrations.github_setup import GitHubSetup
from hivemind_assembly.core.common import Blocked


class Element:
    def __init__(self, page, key):
        self.page, self.key = page, key

    async def count(self):
        if self.key == "password":
            return 0
        if self.key == "app":
            return len(self.page.apps)
        if self.key == "authorize":
            return 0
        return 1

    async def get_attribute(self, name):
        if self.key == "meta":
            return self.page.account
        if self.key == "app":
            return "/settings/applications/123"

    async def fill(self, value):
        self.page.fields[self.key] = value

    async def check(self):
        self.page.flow = True

    async def is_checked(self):
        return self.page.flow

    async def click(self):
        if self.key == "register":
            self.page.posts += 1
            self.page.apps = [self.page.fields["Application name"]]
            self.page.url = "https://github.com/settings/applications/123"
            if self.page.interrupt:
                self.page.interrupt = False
                raise ConnectionError("lost acknowledgement")
        elif self.key == "continue":
            self.page.url = "https://github.com/login/oauth/authorize"


class Page:
    def __init__(self):
        self.url = "https://github.com/settings/developers"
        self.fields = {}
        self.apps = []
        self.flow = False
        self.posts = 0
        self.interrupt = False
        self.account = "owner"

    def is_closed(self):
        return False

    async def goto(self, url, **kw):
        self.url = url

    async def wait_for_load_state(self, *a):
        pass

    def get_by_label(self, name, **kw):
        return Element(self, name)

    def get_by_text(self, *a, **kw):
        return Element(self, "app")

    def get_by_role(self, role, name, **kw):
        return Element(
            self,
            (
                "app"
                if role == "link"
                else {
                    "Register application": "register",
                    "Continue": "continue",
                    "Update application": "update",
                }.get(name, "authorize")
            ),
        )

    def locator(self, selector):
        return Element(self, "meta" if selector.startswith("meta") else "password")

    async def evaluate(self, *a):
        return "public-client-id"


class Auth:
    def __init__(self):
        self.vault = SimpleNamespace(ready=lambda: None)
        self.pending = None
        self.started = 0
        self.login = "owner"
        self.connected = False

    def status(self):
        return {"connected": self.connected}

    def start(self, client):
        self.pending = True
        self.started += 1
        return {
            "verification_uri": "https://github.com/login/device",
            "user_code": "TEST-CODE",
        }

    def poll(self):
        return {"status": "pending", "interval": 5}

    def disconnect(self):
        self.connected = False


def setup(tmp_path):
    page = Page()
    auth = Auth()

    class Browser:
        async def service_page(self, *a):
            return page

    return GitHubSetup(Browser(), auth, tmp_path), page, auth


def test_automatic_registration_reconciles_lost_ack_without_duplicate(tmp_path):
    wizard, page, auth = setup(tmp_path)
    page.interrupt = True
    with pytest.raises(ConnectionError):
        asyncio.run(wizard.step())
    assert wizard.status()["registration_intent"] and page.posts == 1
    result = asyncio.run(wizard.step())
    assert result["stage"] == "authorizing" and page.posts == 1 and auth.started == 1
    assert (
        page.fields["Authorization callback URL"] == "http://127.0.0.1/oauth/callback"
    )
    assert page.flow
    state = wizard.path.read_text()
    assert (
        "TEST-CODE" not in state
        and "device_code" not in state
        and "client_secret" not in state
    )
    # Restart after registration retains the public Client ID and existing app.
    again = GitHubSetup(wizard.browser, auth, tmp_path)
    asyncio.run(again.step())
    assert page.posts == 1 and auth.started == 1


def test_uncertain_missing_registration_never_reposts(tmp_path):
    wizard, page, auth = setup(tmp_path)
    wizard.save(
        account="owner",
        app_name="Hivemind Assembly Local saved",
        registration_intent=True,
    )
    result = asyncio.run(wizard.step())
    assert result["stage"] == "registration_uncertain" and page.posts == 0


def test_setup_account_and_origin_guards(tmp_path):
    wizard, page, auth = setup(tmp_path)
    wizard.save(account="original", app_name="test")
    with pytest.raises(Blocked, match="account changed"):
        asyncio.run(wizard.step())
    page.url = "https://github.com.evil.invalid/settings/developers"
    with pytest.raises(Blocked, match="left github.com"):
        asyncio.run(wizard.step())
