"""Provider UI contracts. Discovery is evidence, not permission to guess labels.

Only rendered controls and explicit account/usage elements are inspected. Chat
messages can never supply model identity, account identity or allowance. Missing
controls stop admission and preserve the last verified binding.
"""

import re
from urllib.parse import urlsplit
from hivemind_assembly.core.common import Blocked


CONTRACTS = {
    "openai": {
        "new_url": "https://chatgpt.com/",
        "conversation": r"/(?:c|g/[^/]+/c)/[A-Za-z0-9-]+",
        "selectors": {
            "composer": "#prompt-textarea",
            "send": 'button[data-testid="send-button"]',
            "user_messages": '[data-message-author-role="user"]',
            "assistant_messages": '[data-message-author-role="assistant"]',
            "complete": 'button[data-testid="copy-turn-action-button"]',
            "streaming": 'button[data-testid="stop-button"]',
            "upload": 'input[type="file"]',
            "attachment_ready": '[data-testid="attachment"]',
            "download": 'a[download], a[href^="https://chatgpt.com/backend-api/files/"]',
            "authentication": 'input[type="password"], input[autocomplete="one-time-code"]',
        },
    },
    "claude": {
        "new_url": "https://claude.ai/new",
        "conversation": r"/chat/[A-Za-z0-9-]+",
        "selectors": {
            "composer": 'div[contenteditable="true"][role="textbox"]',
            "send": 'button[aria-label="Send message"]',
            "user_messages": '[data-testid="user-message"]',
            "assistant_messages": '[data-testid="assistant-message"]',
            "complete": 'button[aria-label="Copy response"]',
            "streaming": 'button[aria-label="Stop response"]',
            "upload": 'input[type="file"]',
            "attachment_ready": '[data-testid="attachment"]',
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


async def discover(page, cfg):
    contract = CONTRACTS[cfg["provider"]]
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
                await loc.click()
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
