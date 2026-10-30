"""HA browser automation using embedded OpenCLI inspection and Reach outcomes.

There is no second browser service, profile store, login-copy operation, dynamic
adapter loader or upstream updater. All pages belong to HA's existing browser.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from hivemind_assembly.core.common import Blocked, ContractError, Conflict, atomic_write, canonical, digest
from .browser_engine.outcomes import ReachError, envelope, BAD_INPUT, TIMEOUT
from .browser_engine.redaction import scrub_url_credentials

ENGINE = Path(__file__).with_name('browser_engine') / 'browser_scripts.json'
IDENTITY = """e => ({tag:e.tagName,type:e.getAttribute('type')||'',id:e.id||'',name:e.getAttribute('name')||'',label:e.getAttribute('aria-label')||'',text:e.tagName==='BUTTON'?(e.innerText||'').slice(0,100):'',connected:e.isConnected})"""
SENSITIVE = re.compile(r'password|passwd|secret|(?:api|auth|access|refresh)[-_ ]?(?:key|token)|one[-_ ]?time|verification[-_ ]?code|security[-_ ]?code|credit[-_ ]?card|\botp\b', re.I)


def origin_of(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        return 'https://' + parsed.hostname.lower()
    except (ValueError, TypeError):
        raise ContractError('Use an HTTPS website without credentials or a custom port') from None


class BrowserActions:
    def __init__(self, browser, root):
        self.browser = browser
        self.path = Path(root) / 'private' / 'automation-receipts.json'
        self.sessions = {}
        self.receipts = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.lock = asyncio.Lock()
        self.scripts = json.loads(ENGINE.read_text(encoding='utf-8'))

    def status(self):
        return {'available': True, 'engine': 'built_in',
                'sessions': [{'id': key, 'profile': value['profile'], 'origin': value['origin'],
                              'open': not value['page'].is_closed()}
                             for key, value in list(self.sessions.items())]}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        completed = [key for key, receipt in self.receipts.items() if receipt['state'] == 'completed']
        for key in completed[:-200]:
            del self.receipts[key]
        atomic_write(self.path, canonical(self.receipts))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def known_profile(self, profile):
        profiles = {route['profile'] for route in self.browser.config['routes'].values()}
        if profile not in profiles:
            raise ContractError('Choose a configured HA browser profile; no fallback profile is used')

    async def run(self, data):
        action = data.get('action')
        if action not in {'open', 'read', 'fill', 'click', 'close'}:
            raise ContractError('Unsupported HA browser action')
        allowed = {'action', 'operation_id', 'profile', 'url', 'session', 'snapshot', 'ref', 'value'}
        if set(data) - allowed:
            raise ContractError('Unknown browser action field')
        operation = data.get('operation_id', '')
        if not isinstance(operation, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', operation):
            raise ContractError('A stable operation ID is required')
        request_hash = digest(data)
        async with self.lock:
            old = self.receipts.get(operation)
            if old:
                if old['hash'] != request_hash:
                    raise Conflict('This operation ID already belongs to a different request')
                if old['state'] != 'completed':
                    return envelope(channel='browser', action=action, error=ReachError(
                        'UNCERTAIN', 'The previous operation may have reached the page. Read the current page before deciding what to do; HA will not repeat it.'))
                return old['result']
            if len(self.receipts) > 1000:
                raise Blocked('Too many unresolved browser operations; reconcile them before starting more')
            self.receipts[operation] = {'hash': request_hash, 'state': 'dispatching'}
            self.save()
            try:
                result = await asyncio.wait_for(self._run(data), timeout=40)
            except Exception as error:
                self.receipts[operation]['state'] = 'uncertain'
                self.save()
                code = TIMEOUT if isinstance(error, TimeoutError) else BAD_INPUT if isinstance(error, ContractError) else 'NEED_ATTENTION'
                message = str(error) if isinstance(error, ContractError) else 'The browser did not complete this step. Read its current state before retrying.'
                return envelope(channel='browser', action=action, error=ReachError(code, scrub_url_credentials(message)[:500]))
            response = envelope(channel='browser', action=action, backend='HA browser', items=[result])
            self.receipts[operation] = {'hash': request_hash, 'state': 'completed',
                                        'result': response if action != 'read' else envelope(channel='browser', action=action, backend='HA browser', items=[{'session': data['session'], 'outcome': 'read_completed', 'snapshot_expired': True}])}
            self.save()
            return response

    async def _run(self, data):
        action = data['action']
        if action == 'open':
            profile, url = data.get('profile'), data.get('url')
            self.known_profile(profile)
            origin = origin_of(url)
            session_id = secrets.token_hex(12)

            async def prepare(page):
                async def guard(route):
                    request = route.request
                    if request.is_navigation_request() and request.frame == page.main_frame:
                        try:
                            permitted = origin_of(request.url) == origin
                        except ContractError:
                            permitted = False
                        if not permitted:
                            await route.abort()
                            return
                    await route.fallback()
                await page.route('**/*', guard)

            page = await self.browser.service_page(profile, url, {urlsplit(origin).hostname}, prepare=prepare)
            if origin_of(page.url) != origin:
                raise Blocked('The page left the selected site; HA did not read another origin')
            self.sessions[session_id] = {'profile': profile, 'origin': origin, 'page': page,
                                         'snapshot': None, 'handles': {}}
            return {'session': session_id, 'profile': profile, 'origin': origin,
                    'outcome': 'opened', 'identity': 'profile_bound_not_site_login_verified'}
        session = self.sessions.get(data.get('session'))
        if not session or session['page'].is_closed():
            raise Blocked('This HA automation page is not open; no other tab was selected')
        page = session['page']
        self.known_profile(session['profile'])
        async with self.browser.profile_lock(session['profile']):
            if action == 'close':
                await page.close()
                self.sessions.pop(data['session'], None)
                return {'session': data['session'], 'outcome': 'closed'}
            if origin_of(page.url) != session['origin']:
                raise Blocked('The page left its authorized site. No action was performed.')
            if action == 'read':
                for handle, _ in session['handles'].values():
                    await handle.dispose()
                await page.locator('[data-ha-ref]').evaluate_all("es=>es.forEach(e=>e.removeAttribute('data-ha-ref'))")
                await page.evaluate(self.scripts['stable'])
                text = await page.evaluate(self.scripts['snapshot'])
                handles = {}
                for element in await page.locator('[data-ha-ref]').element_handles():
                    ref = await element.get_attribute('data-ha-ref')
                    if ref in handles:
                        raise Blocked('The page contains ambiguous action references; HA will not choose one')
                    handles[ref] = (element, await element.evaluate(IDENTITY))
                snapshot = secrets.token_hex(16)
                session.update(snapshot=snapshot, handles=handles)
                return {'session': data['session'], 'snapshot': snapshot,
                        'text': scrub_url_credentials(text), 'origin': session['origin'],
                        'controls': [{'ref': ref, 'tag': ident['tag'], 'label': ident['label'] or ident['name'] or ident['text'] or ident['id'] or ident['tag']} for ref, (_, ident) in handles.items()]}
            if not session['snapshot'] or data.get('snapshot') != session['snapshot']:
                raise Blocked('Read the page again before acting; the saved snapshot is stale')
            ref = str(data.get('ref', ''))
            if not re.fullmatch(r'[0-9]{1,5}', ref) or ref not in session['handles']:
                raise ContractError('Choose one element reference from the current page snapshot')
            element, expected = session['handles'][ref]
            identity = await element.evaluate(IDENTITY)
            if not identity['connected'] or identity != expected:
                raise Blocked('The selected element changed; no action was performed')
            if not await element.is_visible() or not await element.is_enabled():
                raise Blocked('The selected element is not currently actionable')
            metadata = await element.evaluate("e=>[e.type,e.name,e.id,e.getAttribute('autocomplete'),e.getAttribute('aria-label'),e.getAttribute('placeholder'),...[...(e.labels||[])].map(l=>l.textContent)].filter(Boolean).join(' ')")
            if SENSITIVE.search(metadata):
                raise Blocked('Complete credentials or verification directly in the website; HA does not fill or return those values')
            session['snapshot'] = None
            if action == 'fill':
                value = data.get('value')
                if not isinstance(value, str) or len(value) > 4000 or '\x00' in value:
                    raise ContractError('Use a non-secret setup value of at most 4000 characters')
                if identity["tag"] == "SELECT":
                    await element.select_option(label=value, timeout=15000)
                else:
                    await element.fill(value, timeout=15000)
            else:
                await element.click(timeout=15000)
            return {'session': data['session'], 'outcome': 'dispatched',
                    'verification': 'read_page_required'}
