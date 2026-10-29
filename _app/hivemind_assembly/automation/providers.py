"""Provider UI contracts. Discovery is evidence, not permission to guess labels.

Only rendered controls and explicit account/usage elements are inspected. Chat
messages can never supply model identity, account identity or allowance. Missing
controls stop admission and preserve the last verified binding.
"""

import re
from urllib.parse import urlsplit
from hivemind_assembly.core.common import Blocked, Retryable, AllowanceUnavailable


# Selectors checked against the live pages on 2026-10-27 (see surfaces.py); the older
# names stay as alternatives where the page may still use them.
CONTRACTS = {
    "openai": {
        "new_url": "https://chatgpt.com/",
        "usage_url": "https://chatgpt.com/settings/usage",
        "conversation": r"/(?:c|g/[^/]+/c)/[A-Za-z0-9-]+",
        "selectors": {
            "composer": 'div[contenteditable="true"][role="textbox"]',
            "send": 'button[aria-label="Send"], button[data-testid="send-button"]',
            "user_messages": '[data-user-message-bubble="true"], [data-message-author-role="user"]',
            "assistant_messages": '[data-markdown-text-style="assistant-message"], [data-message-author-role="assistant"]',
            "complete": 'button[aria-label="Copy"], button[data-testid="copy-turn-action-button"]',
            "streaming": 'button[data-testid="stop-button"], button[aria-label="Stop streaming"], button[aria-label="Stop generating"], [data-talvt-turn-state]:not([data-talvt-turn-state="complete"])',
            "upload": 'input[type="file"][aria-label="Attach files"]',
            # Not yet seen live: an attachment chip, else the composer form showing the file name.
            "attachment_ready": '[data-testid="attachment"], [data-testid*="attachment"], form',
            "download": 'a[download], a[href^="https://chatgpt.com/backend-api/files/"]',
            "authentication": 'input[type="password"], input[autocomplete="one-time-code"]',
        },
    },
    "claude": {
        "new_url": "https://claude.ai/new",
        "usage_url": "https://claude.ai/settings/usage",
        "conversation": r"/chat/[A-Za-z0-9-]+",
        "selectors": {
            "composer": 'div[contenteditable="true"][role="textbox"]',
            "send": 'button[aria-label="Send message"]',
            "user_messages": '[data-testid="user-message"]',
            "assistant_messages": '[data-testid="assistant-message"]',
            "complete": '[data-testid="message-actions"] button[aria-label="Copy"], button[aria-label="Copy response"]',
            "streaming": '[data-is-streaming="true"], button[aria-label="Stop response"]',
            "upload": 'input[data-testid="file-upload"]',
            # Not yet seen live: an attachment chip, else the composer box showing the file name.
            "attachment_ready": '[data-testid="attachment"], [data-testid*="file-thumbnail"], [data-testid*="attachment"], fieldset',
            "download": "a[download]",
            "authentication": 'input[type="password"], input[autocomplete="one-time-code"]',
        },
    },
}


def conversation_url(cfg, url):
    parts = urlsplit(url)
    return bool(
        parts.scheme == "https"
        and parts.hostname in cfg["allowed_hosts"]
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and re.fullmatch(CONTRACTS[cfg["provider"]]["conversation"], parts.path)
    )


async def exact_control(page, text):
    """Derive a selector from a unique visible selected control, never prose."""
    return await page.evaluate(
        """text => {
      const skip='[data-message-author-role], [data-testid="user-message"], [data-testid="assistant-message"], main article';
      const nodes=[...document.querySelectorAll('button,[role="combobox"],[aria-selected="true"],[aria-checked="true"],[data-testid="account-email"],[data-testid="user-email"],[data-ha-field]')];
      const hits=nodes.filter(e=>!e.closest(skip) && (!e.closest('[role="menu"], [role="listbox"]') || e.matches('[data-testid="account-email"], [data-testid="user-email"]')) && e.getClientRects().length &&
        (e.innerText.trim()===text || e.getAttribute('aria-label')===text));
      if(hits.length!==1)return null;
      let e=hits[0], parts=[];
      for(;e&&e!==document.body;e=e.parentElement){
        if(e.id){parts.unshift('#'+CSS.escape(e.id));break;}
        let i=1;for(let p=e.previousElementSibling;p;p=p.previousElementSibling)if(p.tagName===e.tagName)i++;
        parts.unshift(e.tagName.toLowerCase()+':nth-of-type('+i+')');
      }
      return parts.join(' > ');
    }""",
        text,
    )


async def label(locator):
    if await locator.count() != 1 or not await locator.is_visible():
        raise Blocked("Identity control is missing, hidden or ambiguous")
    text = (await locator.inner_text()).strip()
    return text or (await locator.get_attribute("aria-label") or "").strip()


async def select_exact(page, field, expected):
    found = await exact_control(page, expected)
    if found:
        return found
    triggers = page.get_by_role(
        "button",
        name=re.compile(
            r"^(?:(?:select|choose|change)\s+" + field + r"|" + field + r"(?:\s+.*)?)$",
            re.I,
        ),
    )
    if (
        await triggers.count() == 1
        and await triggers.is_visible()
        and await triggers.is_enabled()
    ):
        await triggers.click()
        options = (
            page.get_by_role("option", name=expected, exact=True)
            .or_(page.get_by_role("menuitemradio", name=expected, exact=True))
            .or_(page.get_by_role("menuitem", name=expected, exact=True))
        )
        if (
            await options.count() == 1
            and await options.is_visible()
            and await options.is_enabled()
        ):
            await options.click()
        else:
            await page.keyboard.press("Escape")
    return await exact_control(page, expected)


async def select_preferred_chat(page, cfg, preferences):
    """Select only observed exact controls in a fresh Chat session, without sending."""
    if cfg.get("provider") != "openai" or cfg.get("mode") != "Chat":
        raise Blocked("Automatic chat-model selection requires the Chat surface")
    if not isinstance(preferences, list) or not 1 <= len(preferences) <= 20:
        raise Blocked("A bounded model preference list is required")
    from .surfaces import detect

    surface = await detect(page, cfg)
    if surface is not None:
        for target in preferences:
            if not isinstance(target, dict) or set(target) != {"model", "effort"}:
                raise Blocked("Invalid model preference")
            try:
                await surface.ensure(page, {**cfg, **target, "mode": "Chat"})
            except Blocked:
                continue
            return {
                **target,
                "selectors": {
                    **cfg.get("selectors", {}),
                    "mode": surface.tag,
                    "model": surface.tag,
                    "effort": surface.tag,
                },
            }
        raise Blocked(
            "No supported preferred Chat model/effort is visible; configure an exact manual override"
        )
    if not await select_exact(page, "mode", "Chat"):
        raise Blocked("Chat mode could not be verified before model selection")
    for target in preferences:
        if (
            not isinstance(target, dict)
            or set(target) != {"model", "effort"}
            or any(
                not isinstance(v, str) or not 1 <= len(v) <= 100
                for v in target.values()
            )
        ):
            raise Blocked("Invalid model preference")
        model = await select_exact(page, "model", target["model"])
        if not model:
            continue
        effort = await select_exact(page, "effort", target["effort"])
        if effort:
            return {
                **target,
                "selectors": {
                    **cfg.get("selectors", {}),
                    "model": model,
                    "effort": effort,
                },
            }
    raise Blocked(
        "No supported preferred Chat model/effort is visible; configure an exact manual override"
    )


MODALS = '[role="dialog"]:visible, [role="alertdialog"]:visible, dialog[open]:visible, [class*="dialog-overlay"][data-state="open"]:visible'
# Dismiss only; never Save, Upgrade, Increase or Remove limit.
CLOSE_NAMES = re.compile(r"^(close|dismiss|cancel|not now|maybe later|got it|skip|no thanks)$", re.I)
LIMIT_NOTICE = re.compile(r"(?:you[’']ve|you have) reached your (?:monthly spend|weekly|usage) limit", re.I)


async def dismiss_popups(page, attempts=3, *, check_allowance=False):
    """Close visible notices; retain an explicit usage limit before dismissing it."""
    limit = False
    for _ in range(attempts):
        dialogs = page.locator(MODALS)
        if not await dialogs.count():
            break
        if check_allowance:
            for dialog in await dialogs.all():
                limit = limit or bool(LIMIT_NOTICE.search(await dialog.inner_text()))
            if limit:
                # A failed dismissal must never erase the positive limit evidence.
                try:
                    buttons = dialogs.get_by_role("button", name=CLOSE_NAMES).filter(visible=True)
                    if await buttons.count():
                        await buttons.first.click(timeout=5000)
                    else:
                        await page.keyboard.press("Escape")
                except Exception:
                    pass
                raise AllowanceUnavailable(
                    "The provider reports a usage or spending limit. HA has not changed spending settings; "
                    "this account waits for its allowance to reset."
                )
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)
        dialogs = page.locator(MODALS)
        if not await dialogs.count():
            break
        buttons = dialogs.get_by_role("button", name=CLOSE_NAMES).filter(visible=True)
        if await buttons.count() >= 1:
            await buttons.first.click(timeout=5000)
            await page.wait_for_timeout(400)
    if await page.locator(MODALS).count():
        raise Retryable(
            "A pop-up is covering the page in HA's tab. Close it there and setup continues by itself."
        )


async def discover(page, cfg):
    await dismiss_popups(page, check_allowance=True)
    contract = CONTRACTS[cfg["provider"]]
    from .surfaces import detect

    surface = await detect(page, cfg)
    if surface is not None:
        # Today's pages: set the exact route through their own model menus. Saved
        # selectors from an older page layout are not reused.
        return await surface.discover(page, cfg, dict(contract["selectors"]))
    selectors = {
        **contract["selectors"],
        **{k: v for k, v in cfg.get("selectors", {}).items() if v},
    }
    missing = []
    for field in ("mode", "model", "effort"):
        if field == "mode" and cfg["provider"] == "claude" and cfg["mode"] == "native":
            continue  # The native surface is the observed claude.ai document.
        selector = await select_exact(page, field, cfg[field])
        if selector:
            selectors[field] = selector
        else:
            # Retained explicit bindings still need to pass observe().
            if not selectors.get(field):
                missing.append(field)
    account = cfg.get("account_label", "")
    opened_account = False
    visible_email = page.locator(
        '[data-testid="account-email"], [data-testid="user-email"]'
    )
    if not await visible_email.count():
        triggers = [
            'button[data-testid="profile-button"]',
            'button[aria-label="Open profile menu"]',
            'button[aria-label="Account menu"]',
        ]
        for trigger in triggers:
            loc = page.locator(trigger)
            if await loc.count() == 1 and await loc.is_visible():
                await dismiss_popups(page)
                await loc.click(timeout=10000)
                opened_account = True
                selectors["account_trigger"] = trigger
                break
    if not account:
        emails = await page.locator(
            '[data-testid="account-email"], [data-testid="user-email"]'
        ).all_inner_texts()
        emails = {
            s.strip()
            for s in emails
            if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", s.strip())
        }
        if len(emails) == 1:
            account = emails.pop()
    selector = await exact_control(page, account) if account else None
    if selector:
        selectors["account"] = selector
    elif not selectors.get("account") or not account:
        missing.append("account")
    if opened_account:
        await page.keyboard.press("Escape")
    # Composer variants are chosen only when actually present in this DOM.
    composer_candidates = [
        selectors["composer"],
        "#mobile-composer-prompt",
        "#prompt-textarea",
        'textarea[placeholder="Message Claude…"]',
    ]
    present = []
    for selector in dict.fromkeys(composer_candidates):
        loc = page.locator(selector)
        if await loc.count() == 1 and await loc.is_visible():
            present.append(selector)
    if len(present) == 1:
        selectors["composer"] = present[0]
    for name in ("composer", "send"):
        loc = page.locator(selectors[name])
        if await loc.count() != 1 or not await loc.is_visible():
            missing.append(name)
    return {"selectors": selectors, "account_label": account, "missing": missing}


USAGE = """() => {
  const named = e => (e.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
    .map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim();
  // The bar's card title: the nearest text above it that isn't "Resets in…" or "88% left".
  const card = e => { for (let c = e.parentElement, i = 0; c && i < 7; c = c.parentElement, i++) {
      const line = ((c.innerText || '').trim().split('\\n')[0] || '').trim();
      if (line && !/^\\d|^resets\\b|\\b(left|used|remaining)$/i.test(line)) return line; }
    return ''; };
  const items = [...document.querySelectorAll('[role="progressbar"], [role="meter"], progress')]
    .filter(e => e.getClientRects().length).map(e => ({
      kind: e.tagName === 'PROGRESS' ? 'progress' : e.getAttribute('role'),
      label: (e.getAttribute('aria-label') || '').trim(), named: named(e), card: card(e),
      value: e.tagName === 'PROGRESS' ? String(e.value) : e.getAttribute('aria-valuenow'),
      min: e.getAttribute('aria-valuemin') || '0',
      max: e.tagName === 'PROGRESS' ? String(e.max) : e.getAttribute('aria-valuemax'),
      text: (e.getAttribute('aria-valuetext') || '').trim()}));
  const body = document.body ? document.body.innerText : '';
  return {items, chat_excluded: /chat conversations are not included/i.test(body)};
}"""


def usage_windows(items):
    """Usage windows from today's usage pages; unrelated bars are ignored.

    Claude: meters named by their heading, "4% used". ChatGPT: a "Usage remaining"
    progress bar in the "Weekly limit" card. Older pages: "Weekly remaining" bars.
    """
    windows = []
    for item in items:
        name = remaining = None
        old = re.fullmatch(r"(.+?)\s+(used|remaining)(?:\s+usage)?", item.get("label", ""), re.I)
        said = re.fullmatch(r"(\d+(?:\.\d+)?)%\s+(used|left|remaining)", item.get("text", ""), re.I)
        try:
            value = float(item.get("value"))
            top = float(item.get("max") or 0)
        except (TypeError, ValueError):
            continue
        if top <= 0 or not 0 <= value <= top:
            continue
        percent = value * 100 / top
        if old and item.get("kind") == "progressbar":
            name, remaining = old[1], (100 - percent if old[2].lower() == "used" else percent)
        elif said and (item.get("named") or item.get("label")):
            name = item.get("named") or item.get("label")
            shown = float(said[1])
            remaining = 100 - shown if said[2].lower() == "used" else shown
        elif item.get("kind") == "progress" and re.fullmatch(r"usage (remaining|left|used)", item.get("label", ""), re.I) and item.get("card"):
            name = item["card"]
            remaining = 100 - percent if item["label"].lower().endswith("used") else percent
        if name is None:
            continue
        windows.append({"name": name, "remaining": round(remaining, 2)})
    if len({w["name"] for w in windows}) != len(windows):
        raise Blocked("Provider usage page shows the same limit twice")
    return windows


async def read_usage(page, cfg):
    """Usage left on today's usage pages, and whether this route has no numeric limit."""
    try:
        await page.locator('[role="meter"], [role="progressbar"], progress').first.wait_for(
            state="visible", timeout=15000
        )
    except Exception:
        pass  # read what is there; an empty page is reported below
    found = await page.evaluate(USAGE)
    if isinstance(found, list):  # older pages, read the old way
        return {"windows": await usage_snapshot(page, cfg), "no_numeric_limit": False}
    # ChatGPT's plan limits cover Work; its page says chat conversations aren't included.
    if cfg.get("provider") == "openai" and cfg.get("mode") == "Chat" and found.get("chat_excluded"):
        return {"windows": [], "no_numeric_limit": True}
    windows = usage_windows(found.get("items", []))
    if not windows:
        raise Blocked("Provider has no complete unambiguous numeric allowance mapping")
    return {"windows": windows, "no_numeric_limit": False}


async def usage_snapshot(page, cfg):
    """Read every explicitly labeled numeric window, rejecting ambiguous units.

    Provider markup may expose used or remaining percentages via progressbar
    accessibility attributes. We never equate no progressbar with unlimited use.
    """
    values = await page.evaluate(
        """() => [...document.querySelectorAll('[role="progressbar"]')]
      .filter(e=>e.getClientRects().length).map(e=>({
        label:e.getAttribute('aria-label')||'', value:e.getAttribute('aria-valuenow'),
        max:e.getAttribute('aria-valuemax'), min:e.getAttribute('aria-valuemin')||'0'
      }))"""
    )
    result = []
    for v in values:
        text = v["label"].strip()
        match = re.fullmatch(r"(.+?)\s+(used|remaining)(?:\s+usage)?", text, re.I)
        if not match or v["max"] != "100" or v["min"] != "0":
            raise Blocked("Provider allowance window is not explicitly mapped")
        try:
            number = float(v["value"])
        except (ValueError, TypeError):
            raise Blocked("Provider allowance value is not numeric") from None
        if not 0 <= number <= 100:
            raise Blocked("Provider allowance value is outside 0–100")
        result.append(
            {
                "name": match[1],
                "remaining": 100 - number if match[2].lower() == "used" else number,
            }
        )
    if not result or len({r["name"] for r in result}) != len(result):
        raise Blocked("Provider has no complete unambiguous numeric allowance mapping")
    return result
