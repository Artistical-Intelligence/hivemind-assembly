"""Your-Chrome mode end to end: Playwright -> HA relay -> helper extension -> Chromium tabs."""

import asyncio
import http.server
import os
import threading

import pytest

from hivemind_assembly.automation.chrome_relay import ChromeRelay
from hivemind_assembly.integrations.chrome_helper import EXTENSION_DIR

PAGE = b"""<!doctype html><title>Assistant</title>
<textarea id="prompt"></textarea><button id="send" onclick="reply()">Send</button>
<div id="answers"></div><input type="file" id="upload">
<a id="dl" href="/artifact.bin" download="artifact.bin">artifact</a>
<script>function reply(){const d=document.createElement('p');d.className='answer';
d.textContent='echo:'+document.getElementById('prompt').value;document.getElementById('answers').append(d)}</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body, kind = (b"\x00\x01artifact-bytes", "application/octet-stream") if self.path == "/artifact.bin" else (PAGE, "text/html")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_CHROME"), reason="needs Chromium")
def test_playwright_drives_tabs_in_the_owners_chrome_through_the_extension(tmp_path):
    from playwright.async_api import async_playwright

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_port}/"
    upload = tmp_path / "input.txt"
    upload.write_text("attached")

    async def scenario():
        relay = await ChromeRelay().start()
        async with async_playwright() as pw:
            owner = await pw.chromium.launch_persistent_context(
                str(tmp_path / "owner-profile"), executable_path=os.environ["WORKBENCH_TEST_CHROME"], headless=True,
                args=["--no-sandbox", f"--disable-extensions-except={EXTENSION_DIR}", f"--load-extension={EXTENSION_DIR}"])
            worker = owner.service_workers[0] if owner.service_workers else await owner.wait_for_event("serviceworker")
            # In real use the native helper hands this address over; the test does it directly.
            await worker.evaluate("url => globalThis.__haConnectRelay(url)", relay.extension_url)
            await relay.wait_for_extension(15)
            owner_tabs_before = len(owner.pages)

            browser = await pw.chromium.connect_over_cdp(relay.cdp_url)
            context = browser.contexts[0]
            page = await context.new_page()
            await page.goto(site)
            await page.locator("#prompt").fill("hello")
            await page.locator("#send").click()
            answer = await page.locator(".answer").inner_text()
            await page.locator("#upload").set_input_files(str(upload))
            uploaded = await page.evaluate("document.getElementById('upload').files[0].name")
            async with page.expect_download() as info:
                await page.locator("#dl").click()
            download = await info.value
            saved = tmp_path / "saved.bin"
            await download.save_as(saved)
            second = await context.new_page()
            await second.goto(site)
            title = await second.title()
            # HA's tabs sit in the owner's browser, in a window of their own.
            owner_tabs_after = len(owner.pages)
            await second.close()
            await browser.close()
            await owner.close()
        await relay.close()
        return answer, uploaded, saved.read_bytes(), title, owner_tabs_before, owner_tabs_after

    try:
        answer, uploaded, data, title, before, after = asyncio.run(scenario())
    finally:
        server.shutdown()
    assert answer == "echo:hello"
    assert uploaded == "input.txt"
    assert data == b"\x00\x01artifact-bytes"
    assert title == "Assistant"
    assert after == before + 2


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_CHROME"), reason="needs Chromium")
def test_native_browser_uses_one_window_of_the_owners_chrome_for_every_account(tmp_path):
    from types import SimpleNamespace
    from playwright.async_api import async_playwright
    from hivemind_assembly.automation.native import NativeBrowser

    async def scenario():
        config = {"browser": {"mode": "your_chrome"}, "routes": {}}
        native = NativeBrowser(config, tmp_path, SimpleNamespace())
        native.relay = ChromeRelay()
        await native.relay.start()
        async with async_playwright() as pw:
            owner = await pw.chromium.launch_persistent_context(
                str(tmp_path / "owner-profile"), executable_path=os.environ["WORKBENCH_TEST_CHROME"], headless=True,
                args=["--no-sandbox", f"--disable-extensions-except={EXTENSION_DIR}", f"--load-extension={EXTENSION_DIR}"])
            worker = owner.service_workers[0] if owner.service_workers else await owner.wait_for_event("serviceworker")
            await worker.evaluate("url => globalThis.__haConnectRelay(url)", native.relay.extension_url)
            context = await native.owner_context()

            async def provider(route):
                await route.fulfill(status=200, content_type="text/html", body="<title>signed in</title>")

            await context.route("https://chatgpt.com/**", provider)
            await context.route("https://claude.ai/**", provider)
            chatgpt = await native.service_page("openai", "https://chatgpt.com/", ["chatgpt.com"])
            claude = await native.service_page("claude", "https://claude.ai/new", ["claude.ai"])
            same = native.contexts["openai"] is native.contexts["claude"]
            titles = [await chatgpt.title(), await claude.title()]
            windows = await worker.evaluate("""async () => {
                const tabs = await chrome.tabs.query({});
                return [...new Set(tabs.filter(t => t.url.startsWith('https://')).map(t => t.windowId))].length;
            }""")
            await native.close()
            await owner.close()
        await native.relay.close()
        return same, titles, windows

    same, titles, windows = asyncio.run(scenario())
    assert same and titles == ["signed in", "signed in"] and windows == 1
