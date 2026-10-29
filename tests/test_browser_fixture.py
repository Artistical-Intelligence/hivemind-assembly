"""Real Chromium against a local service fixture; NOT live-provider acceptance."""

import asyncio, os
import pytest
from workbench.native import NativeBrowser
from workbench.controller import Controller
from workbench.common import Blocked

CHROME = os.environ.get("WORKBENCH_TEST_CHROME")
pytestmark = pytest.mark.skipif(
    not CHROME, reason="Set WORKBENCH_TEST_CHROME for local DOM integration"
)
HTML = """<style>.user { white-space: pre-wrap; }</style><div id="model">Opus 5.5</div><div id="mode">native</div><div id="effort">High</div><div id="account">tester</div><textarea id="compose"></textarea><button id="send">Send</button><div id="messages"></div><div id="done" hidden>Complete</div><input id="upload" type="file"><div id="attached"></div><script>
upload.onchange=()=>attached.textContent=upload.files[0].name;
send.onclick=()=>{let raw=compose.value;let p=JSON.parse(raw.split('\\n').slice(1).join('\\n'));let u=document.createElement('div');u.className='user';u.textContent=raw;messages.append(u);let a=document.createElement('div');a.className='assistant';a.textContent=JSON.stringify({request_id:p.request_id,type:'brief',brief:{procedure:'fixture',acceptance:'fixture'}});messages.append(a);done.hidden=false;compose.value='';};</script>"""


@pytest.mark.parametrize("nested", [False, True])
def test_browser_delivery_reconciliation_and_attachment(store, tmp_path, nested):
    async def run():
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                executable_path=CHROME, headless=True, args=["--no-sandbox"]
            )
            context = await browser.new_context()
            page = await context.new_page()
            html = HTML
            if nested:
                html = html.replace("messages.append(u);", "let inner=document.createElement('div'); inner.className='user-inner'; inner.textContent=u.textContent; u.textContent=''; u.append(inner); messages.append(u);")
                html = html.replace("messages.append(a);", "let answer=document.createElement('div'); answer.className='assistant-inner'; answer.textContent=a.textContent; a.textContent=''; a.append(answer); messages.append(a);")
            await page.route(
                "https://fixture.invalid/chat/1",
                lambda route: route.fulfill(body=html, content_type="text/html"),
            )
            await page.goto("https://fixture.invalid/chat/1")
            selectors = {
                k: "#" + v
                for k, v in {
                    "model": "model",
                    "mode": "mode",
                    "effort": "effort",
                    "account": "account",
                    "composer": "compose",
                    "send": "send",
                    "complete": "done",
                    "upload": "upload",
                    "attachment_ready": "attached",
                }.items()
            }
            selectors.update(user_messages=".user, .user-inner", assistant_messages=".assistant, .assistant-inner")
            cfg = {
                "routes": {
                    "worker.opus": {
                        "provider": "claude",
                        "mode": "native",
                        "model": "Opus 5.5",
                        "effort": "High",
                        "account_label": "tester",
                        "profile": "test",
                        "allowed_hosts": ["fixture.invalid"],
                        "conversation_url": page.url,
                        "selectors": selectors,
                    }
                }
            }
            c = Controller(store)
            native = NativeBrowser(cfg, tmp_path, c)
            native.pages["worker.opus"] = page
            native.contexts["test"] = context
            t = store.create_project("fixture", "test")
            m = c.prepare_message(t["id"], "worker.opus", page.url, {"test": "payload"})
            from workbench.common import file_hash

            attachment = tmp_path / "attachment.txt"
            attachment.write_text("Exact attachment bytes")
            result = await native.exchange(
                "worker.opus",
                m,
                [{"path": str(attachment), "sha256": file_hash(attachment)}],
                timeout=10,
            )
            assert result["request_id"] == m["id"]
            assert await page.locator(".user").count() == 1
            # Simulate lost local acknowledgement after the successful send.
            c.message_state(m["id"], "delivery_uncertain")
            m = store.one("SELECT * FROM messages WHERE id=?", (m["id"],))
            await native.exchange("worker.opus", m, timeout=10)
            assert await page.locator(".user").count() == 1
            # Separate messages remain ambiguous even when they have identical text.
            await page.locator(".user").evaluate("e=>e.after(e.cloneNode(true))")
            with pytest.raises(Blocked, match="separate messages"):
                await native.exchange("worker.opus", m, timeout=10)
            await page.locator(".user").last.evaluate("e=>e.remove()")
            # A visible marker alone must not certify delivery of a clipped payload.
            await page.locator(".user").evaluate(
                "e=>e.textContent=e.textContent.split('\\n')[0]"
            )
            c.message_state(m["id"], "delivery_uncertain")
            m = store.one("SELECT * FROM messages WHERE id=?", (m["id"],))
            with pytest.raises(Blocked, match="complete payload"):
                await native.exchange("worker.opus", m, timeout=10)
            assert await page.locator(".user").count() == 1
            assert (
                store.one("SELECT state FROM messages WHERE id=?", (m["id"],))["state"]
                == "delivery_uncertain"
            )
            # A real browser download must retain the exact expected bytes.
            import hashlib

            expected = b"returned binary bytes\x00\xff"
            # Chromium cancels download-attribute requests intercepted with
            # route.fulfill (Playwright #28253). A real browser-owned Blob avoids
            # that mock-network limitation while exercising actual download IO.
            await page.evaluate(
                "bytes => {const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([new Uint8Array(bytes)], {type:'application/octet-stream'})); a.download='result.bin'; a.className='download'; a.textContent='result.bin'; document.body.append(a)}",
                list(expected),
            )
            destination = tmp_path / "received.bin"
            await native.download(
                "worker.opus",
                ".download",
                destination,
                hashlib.sha256(expected).hexdigest(),
                filename="result.bin",
            )
            assert destination.read_bytes() == expected
            from workbench.common import ContractError

            with pytest.raises(ContractError):
                await native.download(
                    "worker.opus",
                    ".download",
                    destination,
                    "0" * 64,
                    filename="result.bin",
                )
            assert destination.read_bytes() == expected
            assert not list(tmp_path.glob("*.download"))
            # Wrong displayed model must fail before any send.
            await page.locator("#model").evaluate("e=>e.textContent='wrong'")
            with pytest.raises(Blocked):
                await native.observe("worker.opus")
            await browser.close()

    asyncio.run(run())
