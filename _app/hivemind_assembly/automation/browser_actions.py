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
from .browser_engine.session_trust import live_browser_session
from .browser_engine.route_binding import profile_route_binding, bound_route_is_current
from .browser_engine.route_policy import route_policy_fingerprint, route_policy_is_current
from .browser_engine.dispatch_fence import fenced_browser_dispatch
from .browser_engine.element_refs import ElementInspectionError, collect_authorized_refs, require_bounded_snapshot
from .browser_engine.action_inspection import ActionInspectionError, inspect_action_target
from .browser_engine.control_summaries import ControlSummaryError
from .browser_engine.snapshot_publication import publish_authorized_snapshot
from .browser_engine.url_origin import canonical_https_origin

ENGINE = Path(__file__).with_name('browser_engine') / 'browser_scripts.json'
# Never silently age out a completed browser-write receipt: a forgotten
# operation_id would make an old click/fill eligible to run a second time.
MAX_RETAINED_RECEIPTS = 1000
IDENTITY = """e => ({tag:e.tagName,type:e.getAttribute('type')||'',id:e.id||'',name:e.getAttribute('name')||'',label:e.getAttribute('aria-label')||'',text:e.tagName==='BUTTON'?(e.innerText||'').slice(0,100):'',connected:e.isConnected})"""
SENSITIVE = re.compile(r'password|passwd|secret|(?:api|auth|access|refresh)[-_ ]?(?:key|token)|one[-_ ]?time|verification[-_ ]?code|security[-_ ]?code|credit[-_ ]?card|\botp\b', re.I)


def origin_of(url):
    try:
        return canonical_https_origin(url)
    except (ValueError, TypeError):
        # Keep the public HA contract while rejecting cross-parser ambiguities
        # before the native service creates or authorizes a browser page.
        raise ContractError('Use an HTTPS website without credentials or a custom port') from None


class BrowserActions:
    def __init__(self, browser, root):
        self.browser = browser
        self.path = Path(root) / 'private' / 'automation-receipts.json'
        self.sessions = {}
        self.receipts = {}
        self.receipts_error = False
        if self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("Invalid receipt file")
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(saved, dict) or len(saved) > 1500:
                    raise ValueError("Invalid receipt inventory")
                for key, item in saved.items():
                    if (not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', key)
                            or not isinstance(item, dict)
                            or not re.fullmatch(r'[a-f0-9]{64}', item.get('hash', ''))
                            or item.get('state') not in ('dispatching', 'uncertain', 'completed')
                            or item['state'] == 'completed' and not isinstance(item.get('result'), dict)):
                        raise ValueError("Invalid retained operation")
                self.receipts = saved
            except (OSError, ValueError, TypeError, KeyError):
                self.receipts_error = True
        self.lock = asyncio.Lock()
        self.scripts = json.loads(ENGINE.read_text(encoding='utf-8'))

    def status(self):
        state = ('receipts_need_recovery' if self.receipts_error else
                 'reconciliation_required' if len(self.receipts) >= MAX_RETAINED_RECEIPTS else 'ready')
        try:
            profiles = {route['profile'] for route in self.browser.config['routes'].values()}
        except (AttributeError, KeyError, TypeError):
            profiles = set()
        return {'available': state == 'ready', 'engine': 'built_in',
                'state': state,
                'sessions': [{'id': key, 'profile': value['profile'], 'origin': value['origin'],
                              'open': (value.get('profile') in profiles and
                                        self.session_route_is_authorized(value) and
                                        live_browser_session(value, origin_of))}
                             for key, value in list(self.sessions.items())]}

    def save(self):
        if self.receipts_error:
            raise Blocked('Browser automation receipts need recovery; their original file was preserved.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Completed writes are still idempotency fences. Retain them rather than
        # pruning to the newest 200; at capacity, reject new operations safely.
        atomic_write(self.path, canonical(self.receipts))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def require_session_origin(session):
        """Invalidate saved DOM authority if the page leaves its authorized origin.

        Navigation can occur between awaited DOM inspections. A previous
        snapshot/ref never authorizes a later action on a different site.
        """
        if not live_browser_session(session, origin_of):
            session['snapshot'] = None
            session['handles'] = {}
            raise Blocked('The page left its authorized site. Refresh authorization before any browser action.')

    def session_route_is_authorized(self, session):
        """An opened page stays bound to the routes that originally granted access.

        Existing in-memory synthetic fixtures lack route_binding; only a real
        successful open allocates a new, route-bound live session.
        """
        if not isinstance(session, dict):
            return False
        binding = session.get('route_binding')
        policy = session.get('route_policy_binding')
        # Synthetic legacy fixtures have neither binding. A real route-bound
        # page must also prove its *full* original route policy is unchanged;
        # reusing a route ID/profile after changing its prompt or permissions
        # cannot silently preserve an old browser-action authorization.
        if binding is None:
            return policy is None
        return (bound_route_is_current(self.browser.config, session.get('profile'), binding)
                and route_policy_is_current(self.browser.config, session.get('profile'), policy))

    def known_profile(self, profile):
        binding = profile_route_binding(self.browser.config, profile)
        if not binding:
            raise ContractError('Choose a configured HA browser profile; no fallback profile is used')
        return binding

    def require_current_browser_authority(self, session):
        """Recheck the live page AND its configured profile after awaited work."""
        try:
            self.known_profile(session['profile'])
        except (ContractError, AttributeError, KeyError, TypeError):
            session['snapshot'] = None
            session['handles'] = {}
            raise Blocked('The browser profile was revoked or is unavailable') from None
        if not self.session_route_is_authorized(session):
            session['snapshot'] = None
            session['handles'] = {}
            raise Blocked('The original browser route authorization was changed or revoked')
        self.require_session_origin(session)

    async def run(self, data):
        if self.receipts_error:
            raise Blocked('Browser automation receipts need recovery. Other HA capabilities remain available; no uncertain action was repeated.')
        if not isinstance(data, dict):
            raise ContractError('A browser command must be an object')
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
                # A successful open receipt can outlive its ephemeral Playwright
                # page. Do not replay a stale session ID as if a page still exists.
                if action == 'open':
                    previous = old['result'].get('items', [])
                    previous_id = previous[0].get('session') if (
                        isinstance(previous, list) and previous and
                        isinstance(previous[0], dict)) else None
                    session = self.sessions.get(previous_id)
                    # A live page can navigate after its original open. Only
                    # replay the receipt if it is still the *same* authorized
                    # origin and profile; never portray an off-site page as
                    # an approved, reusable session.
                    try:
                        # A profile removed from current routes is no longer
                        # authorized merely because its old page stays open.
                        self.known_profile(data.get('profile'))
                        live_open = self.session_route_is_authorized(session) and live_browser_session(
                            session, origin_of,
                            expected_profile=data.get('profile'),
                            expected_origin=origin_of(data.get('url')))
                    except (ContractError, AttributeError, KeyError, TypeError):
                        live_open = False
                    if not live_open:
                        return envelope(channel='browser', action=action, error=ReachError(
                            'NEED_ATTENTION',
                            'The original browser session is unavailable or left its authorized site. No page was reopened; inspect the site and authorize a fresh operation ID.'))
                return old['result']
            if len(self.receipts) >= MAX_RETAINED_RECEIPTS:
                raise Blocked('Browser receipts are full; existing operation IDs must be preserved for owner-guided reconciliation before new dispatch')
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
            original_route_binding = self.known_profile(profile)
            original_route_policy = route_policy_fingerprint(self.browser.config, profile)
            if original_route_policy is None:
                raise Blocked('The configured browser route policy is invalid')
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
            # service_page is awaited: the configured profile may have been
            # revoked while the page was opening, or the page may have
            # redirected before we could install its session record.
            # Never grant a session based only on the pre-await check.
            try:
                if (self.known_profile(profile) != original_route_binding
                        or not route_policy_is_current(self.browser.config, profile, original_route_policy)):
                    raise Blocked('The original browser route authorization changed')
                if origin_of(page.url) != origin:
                    raise Blocked('The page left the selected site')
            except (ContractError, Blocked):
                # Do not orphan an unauthorized page in the real browser.
                # Receipt handling remains uncertain and will not retry.
                try:
                    await page.close()
                except Exception:
                    pass
                raise Blocked('Browser profile or site authorization changed while opening; no session was granted') from None
            self.sessions[session_id] = {'profile': profile, 'origin': origin, 'page': page,
                                         'route_binding': original_route_binding,
                                         'route_policy_binding': original_route_policy,
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
            self.require_current_browser_authority(session)
            if action == 'read':
                # Invalidate old refs before awaiting DOM work, while still
                # disposing the old element handles instead of dropping them.
                prior_handles = session['handles']
                session['snapshot'] = None
                session['handles'] = {}
                for handle, _ in prior_handles.values():
                    await handle.dispose()
                # Do not continue inspecting an already revoked profile after
                # an awaited cleanup, DOM adjustment or stabilization.
                self.require_current_browser_authority(session)
                await page.locator('[data-ha-ref]').evaluate_all("es=>es.forEach(e=>e.removeAttribute('data-ha-ref'))")
                self.require_current_browser_authority(session)
                await page.evaluate(self.scripts['stable'])
                self.require_current_browser_authority(session)
                text = await page.evaluate(self.scripts['snapshot'])
                # The configured route may be revoked while snapshot evaluation
                # was awaited; origin equality alone does not authorize reads.
                self.require_current_browser_authority(session)
                # Reject pathological or malformed snapshots before returning
                # text or allocating action refs. Never return a partial DOM.
                try:
                    text = require_bounded_snapshot(text)
                except ElementInspectionError as error:
                    raise Blocked(str(error)) from None
                # A profile may be revoked while Playwright gathers handles or
                # while any individual ref/identity await is pending. Validate
                # after each await, and dispose the entire batch on failure.
                elements = await page.locator('[data-ha-ref]').element_handles()
                try:
                    handles = await collect_authorized_refs(
                        elements, session, self.require_current_browser_authority, IDENTITY)
                except ElementInspectionError as error:
                    raise Blocked(str(error)) from None
                # Control labels come from independent, untrusted DOM
                # attributes: the snapshot size limit alone cannot bound them.
                # Redact sensitive URL query/userinfo in this second output.
                # Until validation succeeds, transferred refs must be disposed
                # on error; no new session snapshot may be published.
                try:
                    # Transfer ownership of provisional DOM handles only after
                    # control redaction and the final live-profile/route/origin
                    # check. The helper disposes every uncommitted handle if
                    # permission is revoked or output preparation fails.
                    snapshot, safe_text, controls = await publish_authorized_snapshot(
                        session, handles, text, self.require_current_browser_authority,
                        scrub_url_credentials, lambda: secrets.token_hex(16))
                except ControlSummaryError as error:
                    raise Blocked(str(error)) from None
                return {'session': data['session'], 'snapshot': snapshot,
                        'text': safe_text, 'origin': session['origin'],
                        'controls': controls}
            if not session['snapshot'] or data.get('snapshot') != session['snapshot']:
                raise Blocked('Read the page again before acting; the saved snapshot is stale')
            ref = str(data.get('ref', ''))
            if not re.fullmatch(r'[0-9]{1,5}', ref) or ref not in session['handles']:
                raise ContractError('Choose one element reference from the current page snapshot')
            element, expected = session['handles'][ref]
            # Each Playwright inspection awaits browser work. A revocation
            # during visibility/enablement must block subsequent DOM reads, not
            # merely stop the eventual click or fill.
            try:
                identity, metadata = await inspect_action_target(
                    element, expected, IDENTITY,
                    "e=>[e.type,e.name,e.id,e.getAttribute('autocomplete'),e.getAttribute('aria-label'),e.getAttribute('placeholder'),...[...(e.labels||[])].map(l=>l.textContent)].filter(Boolean).join(' ')",
                    session, self.require_current_browser_authority)
            except ActionInspectionError as error:
                raise Blocked(str(error)) from None
            if SENSITIVE.search(metadata):
                raise Blocked('Complete credentials or verification directly in the website; HA does not fill or return those values')
            # A page may have navigated during element/metadata inspection.
            # Do not dispatch a click or fill based on a different site's DOM.
            self.require_current_browser_authority(session)
            session['snapshot'] = None
            if action == 'fill':
                value = data.get('value')
                if not isinstance(value, str) or len(value) > 4000 or '\x00' in value:
                    raise ContractError('Use a non-secret setup value of at most 4000 characters')
                if identity["tag"] == "SELECT":
                    await fenced_browser_dispatch(
                        session, self.require_current_browser_authority,
                        lambda: element.select_option(label=value, timeout=15000))
                else:
                    await fenced_browser_dispatch(
                        session, self.require_current_browser_authority,
                        lambda: element.fill(value, timeout=15000))
            else:
                await fenced_browser_dispatch(
                    session, self.require_current_browser_authority,
                    lambda: element.click(timeout=15000))
            return {'session': data['session'], 'outcome': 'dispatched',
                    'verification': 'read_page_required'}
