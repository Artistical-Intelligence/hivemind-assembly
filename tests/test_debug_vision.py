"""Real screenshot/OCR regressions and grant fencing; no live provider calls."""
import asyncio
import base64
import hashlib
import io
import json
import os
import sys
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from mcp import Client
from test_debug_mcp import app, server, debug, ROUTE, CHROME
from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.integrations import debug_vision
from hivemind_assembly.integrations.debug_mcp import build_debug_server


@pytest.fixture
def visual(debug):
    debug.stop()
    debug.start([ROUTE], screenshots=True)
    return debug


def test_screenshot_grant_is_explicit_scoped_and_revocable(debug):
    with pytest.raises(Blocked, match='Enable Share screenshots'):
        debug.call('ha_debug_screenshot', {'route': ROUTE})
    with pytest.raises(Blocked, match='Stop debugging'):
        debug.start([ROUTE], screenshots=True)
    with pytest.raises(ContractError):
        debug.start([ROUTE], screenshots='yes')
    old = debug.rpc()
    debug.stop();debug.start([ROUTE], screenshots=True)
    assert debug.status()['screenshots_enabled']
    assert debug.call('ha_debug_status', {})['screenshots_enabled']
    assert old.call('ha_debug_screenshot', {'route': ROUTE})['isError']
    with pytest.raises(Blocked, match='not enabled'):
        debug.call('ha_debug_screenshot', {'route': 'worker.opus'})
    debug.stop()
    assert not debug.visual
    with pytest.raises(Blocked):
        debug.call('ha_debug_screenshot', {'route': ROUTE})


def test_ocr_unavailable_and_word_bounds(monkeypatch):
    monkeypatch.setattr(debug_vision, 'tesseract', lambda: None)
    result = asyncio.run(debug_vision.recognize(b'not decoded without OCR'))
    assert result['state'] == 'unavailable' and 'Install required tools' in result['message']
    header = 'level\tleft\ttop\twidth\theight\tconf\ttext\n'
    raw = header + '5\t10\t20\t30\t40\t95\tHello\n5\t-1\t20\t30\t40\t95\tInvalid\n'
    parsed = debug_vision.words_from_tsv(raw)
    assert parsed['text'] == 'Hello' and parsed['words'][0]['box']['left'] == 10
    parsed = debug_vision.words_from_tsv(header + '5\t1\t2\t3\t4\t95\tword\n' * 1201)
    assert len(parsed['words']) == 1200 and parsed['truncated']


@pytest.mark.parametrize('cancel', [False, True])
def test_ocr_deadline_and_cancellation_reap_process(monkeypatch, cancel):
    original = asyncio.create_subprocess_exec
    processes = []
    entered = None
    async def launch(*args, **kwargs):
        process = await original(sys.executable, '-c', 'import sys,time;sys.stdin.buffer.read();time.sleep(30)', **kwargs)
        processes.append(process);entered.set()
        return process
    monkeypatch.setattr(debug_vision, 'tesseract', lambda: 'fixture')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launch)
    monkeypatch.setattr(debug_vision, 'OCR_SECONDS', .1)
    async def run():
        nonlocal entered
        entered = asyncio.Event()
        task = asyncio.create_task(debug_vision.recognize(b'fixture'))
        await entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        else:
            assert (await task)['state'] == 'timeout'
        assert processes[0].returncode is not None
    asyncio.run(run())


def test_mcp_screenshot_is_actual_image_content():
    picture = base64.b64encode(b'image-fixture').decode()
    async def run():
        server = build_debug_server(lambda tool,args: {'jpeg':picture,'ocr':{'state':'ready','text':'fixture'}})
        async with Client(server) as client:
            result = await client.call_tool('ha_debug_screenshot', {'route':ROUTE})
            assert not result.is_error
            assert result.content[1].type == 'image'
            assert result.content[1].data == picture
            assert json.loads(result.content[0].text)['ocr']['text'] == 'fixture'
    asyncio.run(run())


@pytest.mark.skipif(not CHROME or not debug_vision.available(), reason='Requires Chromium and Tesseract')
def test_real_canvas_screenshot_ocr_while_setup_holds_account_lock(app, visual):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
            context = await browser.new_context(viewport={'width':1000,'height':500})
            await context.route('**/*', lambda r:r.fulfill(content_type='text/html',body='''<style>body{margin:0;background:white}input{position:absolute;left:20px;top:180px;width:300px;height:40px}</style><canvas id="c" width="1000" height="150"></canvas><input value="PRIVATE INPUT"><script>const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,1000,150);x.fillStyle='black';x.font='bold 44px Arial';x.fillText('VISUAL CHECK 7319',30,65);x.fillStyle='#00ff00';x.fillRect(900,100,50,30)</script>'''))
            page = await context.new_page();await page.goto('https://chatgpt.com/')
            app.browser.pages[ROUTE] = page
            lock = app.browser.dispatch_lock(ROUTE)
            try:
                async with lock:
                    with pytest.raises(Blocked, match='busy'):
                        await visual.execute('ha_debug_tab',{'route':ROUTE},visual.epoch)
                    result = await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
                picture = base64.b64decode(result['jpeg'])
                assert hashlib.sha256(picture).hexdigest() == result['sha256']
                assert result['width'] == 1000 and result['height'] == 500
                assert not result['cropped'] and len(context.pages) == 1
                pixels = Image.open(io.BytesIO(picture)).convert('RGB')
                assert pixels.getpixel((920,115))[1] > 240
                assert max(abs(a-b) for a,b in zip(pixels.getpixel((100,200)),(96,104,117))) < 5
                assert result['ocr']['state'] == 'ready'
                assert '7319' in result['ocr']['text'] and 'VISUAL' in result['ocr']['text']
                assert 'PRIVATE' not in result['ocr']['text']
                word = next(w for w in result['ocr']['words'] if '7319' in w['text'])
                assert 0 <= word['box']['left'] < 1000 and word['confidence'] > 50
            finally:
                app.browser.pages.pop(ROUTE,None);await browser.close()
    app.submit(run()).result(timeout=35)


@pytest.mark.skipif(not CHROME, reason='Requires Chromium')
def test_screenshot_rejects_auth_navigation_page_replacement_and_identity_change(app, visual, monkeypatch):
    from playwright.async_api import async_playwright
    async def run():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path=CHROME,args=['--no-sandbox'])
            context=await browser.new_context()
            await context.route('**/*',lambda r:r.fulfill(body='<h1>Visual fixture</h1>',content_type='text/html'))
            page=await context.new_page();app.browser.pages[ROUTE]=page
            try:
                for url in ['https://chatgpt.com/settings','https://chatgpt.com/auth/login','https://outside.invalid/']:
                    await page.goto(url)
                    with pytest.raises(Blocked):await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
                await page.goto('https://chatgpt.com/')
                await page.set_content('<input type="password">')
                with pytest.raises(Blocked,match='Sign-in fields'):await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
                await page.set_content('<h1>Ready</h1>')
                async def moved(picture):
                    await page.goto('https://chatgpt.com/c/other')
                    await page.goto('https://chatgpt.com/')
                    return {'state':'ready'}
                monkeypatch.setattr(debug_vision,'recognize',moved)
                with pytest.raises(Blocked,match='changed'):await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
                async def replaced(picture):
                    other=await context.new_page();await other.goto('https://chatgpt.com/')
                    app.browser.pages[ROUTE]=other
                    return {'state':'ready'}
                monkeypatch.setattr(debug_vision,'recognize',replaced)
                with pytest.raises(Blocked,match='changed'):await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
                app.config['routes'][ROUTE]['model']='Changed'
                with pytest.raises(Blocked,match='identity changed'):await visual.execute('ha_debug_screenshot',{'route':ROUTE},visual.epoch)
            finally:
                app.browser.pages.pop(ROUTE,None);await browser.close()
    app.submit(run()).result(timeout=35)


@pytest.mark.skipif(not CHROME, reason='Requires Chromium')
def test_dashboard_explicit_screenshot_choice(server,app,monkeypatch):
    from playwright.sync_api import sync_playwright,expect
    monkeypatch.setattr(app.debugging.quick,'start',lambda:None)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=CHROME,args=['--no-sandbox'])
        page=browser.new_page();page.goto(f'http://127.0.0.1:{server.server_port}/#{app.token}')
        page.locator('[data-tab="settings"]').click()
        choice=page.locator('#debug-screenshots')
        expect(choice).not_to_be_checked();choice.check()
        page.locator('#debug-card summary').click();page.locator('#debug-start').click()
        expect(choice).to_be_disabled()
        assert app.debugging.visual
        page.locator('#debug-stop').click();expect(choice).to_be_enabled()
        assert not app.debugging.visual
        browser.close()
