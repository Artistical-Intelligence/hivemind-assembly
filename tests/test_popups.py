"""Announcement pop-ups covering ChatGPT/Claude are closed, or the owner is asked to."""

import asyncio
import os

import pytest

from hivemind_assembly.automation.providers import dismiss_popups
from hivemind_assembly.core.common import Retryable

ESCAPE = """<div id=o class="codex-dialog-overlay" data-state="open" style="position:fixed;inset:0"></div>
<script>addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('o').remove()})</script>"""
BUTTON = """<div role="dialog" aria-modal="true"><p>New: Codex</p><button onclick="this.parentNode.remove()">Not now</button></div>"""
STUCK = """<div role="dialog" aria-modal="true"><p>Accept the new terms</p><button>Accept</button></div>"""


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_CHROME"), reason="needs Chromium")
def test_popups_close_or_wait_for_the_owner():
    from playwright.async_api import async_playwright

    async def scenario():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], args=["--no-sandbox"])
            page = await browser.new_page()
            results = []
            for html in (ESCAPE, BUTTON):
                await page.set_content(html)
                await dismiss_popups(page)
                results.append(await page.locator("[role=dialog], .codex-dialog-overlay").count())
            await page.set_content(STUCK)
            with pytest.raises(Retryable, match="pop-up"):
                await dismiss_popups(page)
            # Nothing that accepts or changes anything was clicked.
            results.append(await page.get_by_role("button", name="Accept").count())
            await browser.close()
            return results

    assert asyncio.run(scenario()) == [0, 0, 1]
