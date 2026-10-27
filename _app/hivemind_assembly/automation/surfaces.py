"""Today's ChatGPT and Claude pages: read and set mode, model and effort, and read the
signed-in account, through the controls these pages actually render.

Checked against the live pages on 2026-10-27:
- ChatGPT: a Chat/Work switch (buttons with aria-pressed); one model button
  (aria-label "Select ChatGPT model") whose menu lists models as menu radios and sets
  the effort with a "Power" slider ("High, 3 of 6." in its description). Work mode
  shows model and effort on the button; Chat mode shows only the effort.
  The account email is in the profile menu's account submenu.
- Claude: one model button (data-testid "model-selector-dropdown") showing model and
  effort; its menu lists models as menu radios and has an Effort submenu. The account
  email heads the user menu.

Discovery is evidence, not guessing: HA selects only a model or effort whose exact name
the page offers, and afterwards checks the page shows exactly the configured values.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager

from hivemind_assembly.core.common import Blocked

SURFACE = "surface:"
MENU = '[role="menu"]'
POWER = '[aria-label="Power"]'
RADIO = '[role="menuitemradio"]'
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

# Visible text pieces of one control, without aria-hidden or visibility:hidden parts
# (ChatGPT keeps every effort name inside its model button for its animation).
LEAVES = """sel => {
  const b = document.querySelector(sel);
  if (!b) return null;
  return [...b.querySelectorAll('*')].filter(e => !e.children.length && (e.textContent || '').trim()
      && !e.closest('[aria-hidden="true"]') && getComputedStyle(e).visibility !== 'hidden')
    .map(e => e.textContent.trim());
}"""

# Mark exactly one menu entry (by role and exact name) so a real click can follow.
MARK = """({role, name, within}) => {
  document.querySelectorAll('[data-ha-pick]').forEach(e => e.removeAttribute('data-ha-pick'));
  const first = e => {
    const leaf = [...e.querySelectorAll('*')].find(x => !x.children.length && (x.textContent || '').trim()
      && !x.closest('[aria-hidden="true"]'));
    return ((leaf ? leaf.textContent : e.textContent) || '').trim();
  };
  const menus = [...document.querySelectorAll('[role="menu"]')];
  // 'sub': only submenus, not the menu that holds the Effort entry.
  const isMain = m => [...m.querySelectorAll('[role="menuitem"]')].some(i => first(i) === 'Effort');
  const scope = within === 'sub' ? menus.filter(m => !isMain(m)) : menus;
  const hits = scope.flatMap(m => [...m.querySelectorAll('[role="' + role + '"]')]).filter(e => first(e) === name);
  if (hits.length === 1) hits[0].setAttribute('data-ha-pick', '1');
  return hits.length;
}"""

CHATGPT_MODE = """() => {
  const named = [...document.querySelectorAll('button[aria-pressed]')]
    .filter(b => ['Chat', 'Work'].includes((b.textContent || '').trim()));
  const on = named.filter(b => b.getAttribute('aria-pressed') === 'true');
  if (on.length === 1) return on[0].textContent.trim();
  if (named.length) return null;
  // Inside a conversation the switch is gone; the message box still says which mode.
  const box = document.querySelector('[contenteditable="true"][role="textbox"]');
  const label = (box && box.getAttribute('aria-label')) || '';
  return /^work with chatgpt$/i.test(label) ? 'Work' : /^ask chatgpt$/i.test(label) ? 'Chat' : null;
}"""

CHATGPT_MENU = """() => {
  const menu = document.querySelector('[role="menu"]');
  if (!menu) return null;
  const first = e => {
    const leaf = [...e.querySelectorAll('*')].find(x => !x.children.length && (x.textContent || '').trim()
      && !x.closest('[aria-hidden="true"]'));
    return ((leaf ? leaf.textContent : e.textContent) || '').trim();
  };
  const radios = [...menu.querySelectorAll('[role="menuitemradio"]')];
  const checked = radios.filter(r => r.getAttribute('aria-checked') === 'true');
  const power = menu.querySelector('[aria-label="Power"]');
  const said = power ? (power.getAttribute('aria-describedby') || '').split(/\\s+/).filter(Boolean)
    .map(i => (document.getElementById(i) || {}).textContent || '').join(' ') : '';
  const m = said.match(/^\\s*(.+?),\\s*(\\d+)\\s+of\\s+(\\d+)\\b/);
  return {models: radios.map(first), model: checked.length === 1 ? first(checked[0]) : null,
          effort: m ? m[1].trim() : null, index: m ? +m[2] : null, count: m ? +m[3] : null};
}"""

CLAUDE_MENU = """() => {
  const menus = [...document.querySelectorAll('[role="menu"]')];
  const leaves = e => [...e.querySelectorAll('*')].filter(x => !x.children.length && (x.textContent || '').trim()
      && !x.closest('[aria-hidden="true"]')).map(x => x.textContent.trim());
  const first = e => leaves(e)[0] || (e.textContent || '').trim();
  const isMain = m => [...m.querySelectorAll('[role="menuitem"]')].some(i => first(i) === 'Effort');
  const main = menus.find(isMain) || menus[0];
  if (!main) return null;
  const radios = [...main.querySelectorAll('[role="menuitemradio"]')];
  const checked = radios.filter(r => r.getAttribute('aria-checked') === 'true');
  const effortItem = [...main.querySelectorAll('[role="menuitem"]')].find(i => first(i) === 'Effort');
  const subs = menus.filter(m => m !== main);
  const subRadios = subs.flatMap(m => [...m.querySelectorAll('[role="menuitemradio"]')]);
  const on = subRadios.filter(r => r.getAttribute('aria-checked') === 'true');
  return {models: radios.map(first), model: checked.length === 1 ? first(checked[0]) : null,
          effort: effortItem ? (leaves(effortItem)[1] || null) : null,
          options: subRadios.map(first), chosen: on.length === 1 ? first(on[0]) : null,
          submenu: subs.length};
}"""


async def close_menus(page, tries=4):
    for _ in range(tries):
        if not await page.locator(MENU).count():
            return
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.25)


async def settle(check, want, seconds=5.0):
    """Wait until an async reading equals the wanted value; return the last reading."""
    value = None
    for _ in range(int(seconds / 0.2)):
        value = await check()
        if value == want:
            return value
        await asyncio.sleep(0.2)
    return value


async def pick(page, role, name, within="all", timeout=5000):
    """Click the one menu entry with this exact name, or say what the page offers."""
    hits = await page.evaluate(MARK, {"role": role, "name": name, "within": within})
    if hits != 1:
        return False
    await page.locator('[data-ha-pick="1"]').click(timeout=timeout)
    return True


class Surface:
    name = ""
    provider = ""
    picker = ""

    @property
    def tag(self):
        return SURFACE + self.name

    async def present(self, page):
        return await page.locator(self.picker).count() == 1

    async def read(self, page, deep=False):
        return await (self.deep(page) if deep else self.shallow(page))

    @asynccontextmanager
    async def menu(self, page, ready):
        """Open the model menu, run the body, and always close it again."""
        await close_menus(page)
        await page.locator(self.picker).click(timeout=10000)
        try:
            await page.locator(MENU + " " + ready).first.wait_for(state="attached", timeout=5000)
            yield
        finally:
            await close_menus(page)

    async def verify(self, page, cfg):
        state = await self.deep(page)
        wanted = {"model": cfg["model"], "effort": cfg["effort"]}
        if self.provider == "openai":
            wanted["mode"] = cfg["mode"]
        # A model without an effort setting is configured with an empty effort.
        wrong = [f"{field} is {state.get(field) or 'not shown'}" for field, value in wanted.items() if (state.get(field) or "") != (value or "")]
        if wrong:
            raise Blocked(f"{self.label} still shows the wrong settings: " + "; ".join(wrong) + ".")
        return state

    async def discover(self, page, cfg, selectors):
        """Set the exact route, then read the account; never sends anything."""
        missing, detail = [], ""
        try:
            await self.ensure(page, cfg)
            for field in ("mode", "model", "effort"):
                selectors[field] = self.tag
        except Blocked as error:
            missing += ["model", "effort"]
            detail = str(error)
        account = await self.account(page)
        if account:
            selectors["account"] = self.tag
        else:
            missing.append("account")
        composer = page.locator(selectors["composer"])
        if await composer.count() != 1 or not await composer.first.is_visible():
            missing.append("composer")
        # Claude shows its send button only once the message box has text.
        if not await page.locator(selectors["send"]).count():
            missing.append("send")
        return {"selectors": selectors, "account_label": account or "", "missing": missing, "detail": detail}


class ChatGPT(Surface):
    name = "chatgpt"
    provider = "openai"
    label = "ChatGPT"
    picker = 'button[aria-label="Select ChatGPT model"]'

    async def mode(self, page):
        return await page.evaluate(CHATGPT_MODE)

    async def shallow(self, page):
        leaves = await page.evaluate(LEAVES, self.picker) or []
        # Work mode shows "GPT-6 Astra" + "High"; Chat mode shows only the effort.
        return {
            "mode": await self.mode(page),
            "model": leaves[0] if len(leaves) >= 2 else None,
            "effort": leaves[1] if len(leaves) >= 2 else (leaves[0] if leaves else None),
        }

    async def deep(self, page):
        state = await self.shallow(page)
        async with self.menu(page, POWER):
            menu = await page.evaluate(CHATGPT_MENU) or {}
        state["model"] = menu.get("model")
        state["effort"] = menu.get("effort") or state["effort"]
        return state

    async def switch(self, page, mode):
        if mode not in ("Chat", "Work") or await self.mode(page) == mode:
            return
        switch = page.get_by_role("button", name=mode, exact=True)
        if await switch.count() != 1:
            raise Blocked(f"ChatGPT's {mode} switch isn't on this page.")
        await switch.click(timeout=10000)
        if await settle(lambda: self.mode(page), mode) != mode:
            raise Blocked(f"ChatGPT didn't switch to {mode}.")

    async def select(self, page, mode, model):
        async with self.menu(page, POWER):
            state = await page.evaluate(CHATGPT_MENU) or {}
            if state.get("model") == model:
                return
            offered = [m for m in state.get("models", []) if m]
            if model not in offered:
                raise Blocked(f"ChatGPT offers {', '.join(offered) or 'no models'} in {mode} for this account, not {model}.")
            await page.locator(MENU + ' [aria-label="Select model"]').click(timeout=5000)
            if not await pick(page, "menuitemradio", model):
                raise Blocked(f"HA couldn't choose {model} in ChatGPT's model list.")
        await asyncio.sleep(0.3)

    async def ensure(self, page, cfg):
        mode, model, effort = cfg["mode"], cfg["model"], cfg["effort"]
        await self.switch(page, mode)
        await self.select(page, mode, model)
        # Each model has its own efforts: set the effort in a freshly opened menu.
        async with self.menu(page, POWER):
            state = await page.evaluate(CHATGPT_MENU) or {}
            if state.get("model") != model:
                raise Blocked(f"ChatGPT didn't switch to {model}.")
            if effort and state.get("effort") != effort:
                await self.power(page, state, model, effort)
        return await self.verify(page, cfg)

    async def levels(self, page):
        """Every Power level of the chosen model, leaving the slider where it was."""
        state = await page.evaluate(CHATGPT_MENU) or {}
        count, start = state.get("count") or 0, state.get("index")
        if not count or start is None:
            return [state["effort"]] if state.get("effort") else []
        await page.locator(MENU + ' [aria-label="Power"]').focus()

        async def now():
            return await page.evaluate(CHATGPT_MENU) or {}

        async def step(key):
            await page.keyboard.press(key)
            await asyncio.sleep(0.15)

        for _ in range(count):
            if (await now()).get("index") in (1, None):
                break
            await step("ArrowLeft")
        names = []
        for _ in range(count):
            current = await now()
            names.append(current.get("effort"))
            if (current.get("index") or count) >= count:
                break
            await step("ArrowRight")
        for _ in range(count):
            index = (await now()).get("index")
            if index in (None, start):
                break
            await step("ArrowLeft" if index > start else "ArrowRight")
        return [n for n in names if n]

    async def options(self, page):
        """Every mode, model and effort this account's ChatGPT offers, read from its own
        picker. The owner's choices in this tab are put back afterwards."""
        first = await self.mode(page)
        catalog = {}
        for mode in ("Chat", "Work"):
            await self.switch(page, mode)
            async with self.menu(page, POWER):
                state = await page.evaluate(CHATGPT_MENU) or {}
            keep = (state.get("model"), state.get("effort"))
            found = {}
            for model in [m for m in state.get("models", []) if m]:
                await self.select(page, mode, model)
                async with self.menu(page, POWER):
                    found[model] = await self.levels(page)
            if keep[0]:
                await self.ensure(page, {"mode": mode, "model": keep[0], "effort": keep[1] or ""})
            catalog[mode] = found
        if first in ("Chat", "Work"):
            await self.switch(page, first)
        return catalog

    async def power(self, page, state, model, effort):
        """Move the Power slider one step at a time until it reads the exact effort."""
        count = state.get("count") or 8
        start = state.get("index")
        await page.locator(MENU + ' [aria-label="Power"]').focus()

        async def now():
            return await page.evaluate(CHATGPT_MENU) or {}

        async def step(key):
            await page.keyboard.press(key)
            await asyncio.sleep(0.15)

        for _ in range(count):
            if (await now()).get("index") in (1, None):
                break
            await step("ArrowLeft")
        seen = []
        for _ in range(count):
            current = await now()
            seen.append(current.get("effort"))
            if current.get("effort") == effort:
                return
            if current.get("index") is None or current.get("index") >= (current.get("count") or count):
                break
            await step("ArrowRight")
        # Not offered: put the slider back where the owner had it.
        for _ in range(count):
            current = (await now()).get("index")
            if current in (None, start) or start is None:
                break
            await step("ArrowLeft" if current > start else "ArrowRight")
        offered = ", ".join(x for x in seen if x)
        raise Blocked(f"ChatGPT offers {offered or 'no efforts'} for {model}, not {effort}.")

    async def account(self, page):
        """The signed-in email, from the profile menu's account submenu."""
        trigger = page.locator('button[aria-label="Open profile menu"]')
        if await trigger.count() != 1:
            return None
        await close_menus(page)
        await trigger.click(timeout=10000)
        try:
            switcher = page.locator(MENU + ' [role="menuitem"]:has([data-testid="workspace-switcher-trigger"])')
            await switcher.first.wait_for(state="attached", timeout=5000)
            emails = page.locator(MENU + ' [role="menuitem"]').filter(has_text=EMAIL)
            if not await emails.count():
                await switcher.first.hover(timeout=5000)
                await asyncio.sleep(0.5)
            if not await emails.count():
                await switcher.first.click(timeout=5000)
                await asyncio.sleep(0.5)
            found = {t.strip() for t in await emails.all_inner_texts() if EMAIL.fullmatch(t.strip())}
            return found.pop() if len(found) == 1 else None
        except Exception:
            return None
        finally:
            await close_menus(page)


class Claude(Surface):
    name = "claude"
    provider = "claude"
    label = "Claude"
    picker = '[data-testid="model-selector-dropdown"]'

    async def shallow(self, page):
        leaves = await page.evaluate(LEAVES, self.picker) or []
        words = [x for x in leaves if re.fullmatch(r"[A-Za-z][\w .+-]*", x)]
        return {
            "mode": "native",
            "model": words[0] if words else None,
            "effort": words[1] if len(words) > 1 else None,
        }

    async def deep(self, page):
        state = await self.shallow(page)
        async with self.menu(page, RADIO):
            menu = await page.evaluate(CLAUDE_MENU) or {}
        state["model"] = menu.get("model")
        state["effort"] = menu.get("effort") or state["effort"]
        return state

    async def select(self, page, model):
        async with self.menu(page, RADIO):
            state = await page.evaluate(CLAUDE_MENU) or {}
            if state.get("model") == model:
                return
            if model not in state.get("models", []):
                more = page.locator(MENU + ' [role="menuitem"]').filter(has_text=re.compile(r"^\s*More models"))
                if await more.count() == 1:
                    await more.hover(timeout=5000)
                    await asyncio.sleep(0.5)
            if not await pick(page, "menuitemradio", model):
                offered = ", ".join(m for m in state.get("models", []) if m)
                raise Blocked(f"Claude offers {offered or 'no models'} for this account, not {model}.")
        await asyncio.sleep(0.3)

    async def efforts(self, page):
        """Open the Effort submenu of the open model menu; its choices (none for models
        without an effort setting)."""
        item = page.locator(MENU + ' [role="menuitem"]').filter(has_text=re.compile(r"^\s*Effort"))
        if await item.count() != 1:
            return []
        await item.hover(timeout=5000)
        await asyncio.sleep(0.5)
        if not (await page.evaluate(CLAUDE_MENU) or {}).get("submenu"):
            await item.click(timeout=5000)
            await asyncio.sleep(0.5)
        return [o for o in (await page.evaluate(CLAUDE_MENU) or {}).get("options", []) if o]

    async def ensure(self, page, cfg):
        model, effort = cfg["model"], cfg["effort"]
        await self.select(page, model)
        async with self.menu(page, RADIO):
            state = await page.evaluate(CLAUDE_MENU) or {}
            if state.get("model") != model:
                raise Blocked(f"Claude didn't switch to {model}.")
            if effort and state.get("effort") != effort:
                offered = await self.efforts(page)
                if not offered:
                    raise Blocked(f"Claude shows no Effort choice for {model}.")
                if not await pick(page, "menuitemradio", effort, within="sub"):
                    raise Blocked(f"Claude offers {', '.join(offered)} for {model}, not {effort}.")
        return await self.verify(page, cfg)

    async def options(self, page):
        """Every model and effort this account's Claude offers, read from its own picker.
        The owner's choice in this tab is put back afterwards."""
        async with self.menu(page, RADIO):
            state = await page.evaluate(CLAUDE_MENU) or {}
        keep = (state.get("model"), state.get("effort"))
        found = {}
        for model in [m for m in state.get("models", []) if m]:
            await self.select(page, model)
            async with self.menu(page, RADIO):
                found[model] = await self.efforts(page)
        if keep[0]:
            await self.ensure(page, {"mode": "native", "model": keep[0], "effort": keep[1] or ""})
        return {"native": found}

    async def account(self, page):
        """The signed-in email at the top of the user menu."""
        trigger = page.locator('[data-testid="user-menu-button"]')
        if await trigger.count() != 1:
            return None
        await close_menus(page)
        await trigger.click(timeout=10000)
        try:
            header = page.locator('[data-testid="user-menu-header"]')
            await header.first.wait_for(state="attached", timeout=5000)
            text = (await header.first.inner_text()).strip()
            return text if EMAIL.fullmatch(text) else None
        except Exception:
            return None
        finally:
            await close_menus(page)


SURFACES = {"openai": ChatGPT(), "claude": Claude()}


async def detect(page, cfg):
    """The provider's current page layout, when this page is one HA knows."""
    surface = SURFACES.get(cfg.get("provider"))
    if surface is None or not hasattr(page, "locator"):
        return None
    return surface if await surface.present(page) else None


def from_selectors(selectors):
    """The surface a route was bound through, if its identity fields name one."""
    for field in ("model", "effort", "mode", "account"):
        value = (selectors or {}).get(field) or ""
        if value.startswith(SURFACE):
            return next((s for s in SURFACES.values() if s.tag == value), None)
    return None
