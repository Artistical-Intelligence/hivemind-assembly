"""github.com New repository fallback, against a stand-in of the page's controls."""

import asyncio
import re

import pytest

from hivemind_assembly.core.common import Blocked, Conflict
from hivemind_assembly.integrations.github_web import GitHubWeb


class Locator:
    def __init__(self, page, key):
        self.page, self.key = page, key

    async def count(self):
        p = self.page
        if self.key == "password":
            return 0
        if self.key.startswith("text:"):
            text = self.key[5:]
            if text.endswith(" is available."):
                return int(p.typed is not None and p.typed not in p.taken)
            if text == "already exists":
                return int(p.typed in p.taken)
            return 0
        if self.key.startswith("item:"):
            return int(self.key[5:] in ("Private", "Public", p.extra_owner))
        return 1

    async def get_attribute(self, name):
        p = self.page
        if self.key == "meta":
            return p.login
        if self.key == "visibility":
            return "Choose visibility: " + p.visibility
        if self.key == "owner":
            return p.owner + ", Owner (Required)"

    async def fill(self, value):
        if self.key == "name":
            self.page.typed = value
        else:
            self.page.fields[self.key] = value

    async def click(self):
        p = self.page
        p.clicks.append(self.key)
        if self.key.startswith("item:"):
            label = self.key[5:]
            if label in ("Private", "Public"):
                p.visibility = label
            else:
                p.owner = label
        if self.key == "create":
            p.url = f"https://github.com/{p.owner}/{p.typed}"


class Response:
    def __init__(self, status):
        self.status = status


class Page:
    def __init__(self, login="owner"):
        self.url = "https://github.com/new"
        self.login = login
        self.owner = login
        self.visibility = "Public"
        self.typed = None
        self.taken = set()
        self.fields = {}
        self.clicks = []
        self.closed = False
        self.extra_owner = "team"
        self.signed_in = True

    def locator(self, selector):
        if selector.startswith("meta"):
            return Locator(self, "meta")
        if "password" in selector:
            return Locator(self, "password")
        return Locator(self, {
            "#repository-name-input": "name",
            "#visibility-anchor-button": "visibility",
            "#owner-dropdown-header-button": "owner",
        }[selector])

    def get_by_label(self, name, **kw):
        return Locator(self, name)

    def get_by_text(self, text, **kw):
        return Locator(self, "text:" + text)

    def get_by_role(self, role, name, **kw):
        if role == "button" and name == "Create repository":
            return Locator(self, "create")
        if isinstance(name, re.Pattern):
            name = name.pattern.lstrip("^")
        return Locator(self, "item:" + name)

    async def wait_for_url(self, pattern, timeout):
        assert pattern.match(self.url), self.url

    async def goto(self, url, **kw):
        self.url = url
        return Response(200 if url.endswith("/owner/exists") else 404)

    async def close(self):
        self.closed = True


class Browser:
    def __init__(self, page):
        self.page = page
        self.opened = []

    async def service_page(self, profile, url, hosts=None):
        self.opened.append((profile, url, hosts))
        if not self.page.signed_in:
            self.page.url = "https://github.com/login?return_to=%2Fnew"
        return self.page


def test_creates_private_repository_and_confirms_its_page():
    page = Page()
    web = GitHubWeb(Browser(page))
    result = asyncio.run(web.create("", "RE-Wizard", "My research", "private"))
    assert result == {
        "owner": "owner", "name": "RE-Wizard", "url": "https://github.com/owner/RE-Wizard",
        "visibility": "private", "created_with": "browser",
    }
    assert page.visibility == "Private" and page.fields["Description"] == "My research"
    assert page.clicks[-1] == "create" and page.closed


def test_public_stays_public_without_opening_the_menu():
    page = Page()
    asyncio.run(GitHubWeb(Browser(page)).create("owner", "open", "", "public"))
    assert "visibility" not in page.clicks and page.visibility == "Public"


def test_existing_name_is_refused_before_creating():
    page = Page()
    page.taken.add("taken")
    with pytest.raises(Conflict, match="already exists"):
        asyncio.run(GitHubWeb(Browser(page)).create("owner", "taken"))
    assert "create" not in page.clicks


def test_sign_in_page_is_left_open_for_the_owner():
    page = Page()
    page.signed_in = False
    with pytest.raises(Blocked, match="Sign in"):
        asyncio.run(GitHubWeb(Browser(page)).create("owner", "new"))
    assert not page.closed and "create" not in page.clicks


def test_organization_owner_is_chosen_on_the_page():
    page = Page()
    result = asyncio.run(GitHubWeb(Browser(page)).create("team", "shared"))
    assert result["owner"] == "team" and page.url == "https://github.com/team/shared"
    page = Page()
    with pytest.raises(Blocked, match="does not offer"):
        asyncio.run(GitHubWeb(Browser(page)).create("stranger", "shared"))


def test_exists_checks_the_repository_page():
    page = Page()
    web = GitHubWeb(Browser(page))
    assert asyncio.run(web.exists("owner", "exists")) is True
    assert asyncio.run(web.exists("owner", "missing")) is False
