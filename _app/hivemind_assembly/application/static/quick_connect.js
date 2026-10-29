// ChatGPT and Claude in the browser: Quick Tunnel status, provider steps and approval codes.
(() => {
  const el = id => document.getElementById(id);
  let providers = {};
  let chosen = '';

  const ago = t => {
    const s = Math.max(0, Math.round(Date.now() / 1000 - t));
    return s < 60 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago';
  };

  function serviceLine(name, e) {
    if (e.last_tool_at) return `${name}: connected. Last used HA ${ago(e.last_tool_at)}.`;
    if (e.tools_listed_at) return `${name}: connected. It can see HA's tools; ask it to list your HA projects to confirm.`;
    if (e.authorized) return `${name}: approved. Waiting for it to contact HA.`;
    if (e.approval_requested_at) return `${name}: waiting for the approval code on HA's approval page.`;
    return `${name}: not connected.`;
  }

  function render(q) {
    if (!q) return;
    providers = q.providers || providers;
    const running = !['off', 'error'].includes(q.state);
    el('quick-start').hidden = running;
    el('quick-stop').hidden = !running;
    let text = q.state === 'off' ? 'HA\'s connection is off. Connect starts it.' : (q.message || '');
    const auto = q.auto;
    if (q.address_changed) text += auto?.providers?.length
      ? ' The address changed; HA is reconnecting ' + auto.providers.join(' and ') + ' itself.'
      : ' The address changed, so connect ChatGPT and Claude again.';
    el('quick-status').textContent = text;
    el('quick-status').classList.toggle('warn-text', q.state === 'error');
    const d = q.download;
    el('quick-download').hidden = !d;
    if (d && d.total_bytes) el('quick-download-bar').value = Math.round(100 * d.done_bytes / d.total_bytes);
    el('quick-ready').hidden = q.state !== 'ready';
    if (el('quick-address').value !== q.endpoint) el('quick-address').value = q.endpoint || '';
    if (auto) renderAuto(auto);
    if (q.mode) renderMode(q);
    const services = q.services || {};
    el('quick-services').replaceChildren(...Object.keys(providers).map(name => {
      const li = document.createElement('li');
      li.textContent = serviceLine(name, services[name] || {});
      return li;
    }));
  }

  const temporaryIntro = el('quick-intro').textContent;
  function renderMode(q) {
    const permanent = q.mode === 'permanent';
    el('quick-intro').textContent = permanent
      ? 'Work with your HA projects from ChatGPT and Claude chats, through your permanent address (' + q.permanent.origin + '). Select Connect once; approvals are kept through restarts. Keep HA running while you chat.'
      : temporaryIntro;
    el('quick-auto').hidden = permanent;
    el('permanent-setup').hidden = permanent;
    el('permanent-off').hidden = !permanent;
  }

  let autoLoaded = false;
  function renderAuto(auto) {
    if (!autoLoaded) {
      for (const box of el('quick-auto').elements.provider) box.checked = auto.providers.includes(box.value);
      autoLoaded = true;
    }
    el('quick-auto-progress').replaceChildren(...Object.entries(auto.progress || {}).map(([name, p]) => {
      const li = document.createElement('li');
      li.textContent = `${name}: ${p.message} (${ago(p.at)})`;
      li.classList.toggle('warn-text', p.stage === 'manual');
      return li;
    }));
  }

  function showSteps(name) {
    chosen = name;
    const steps = (providers[name] || {}).steps || [];
    el('quick-steps').replaceChildren(...steps.map(s => {
      const li = document.createElement('li');
      li.textContent = s;
      return li;
    }));
    el('quick-steps').hidden = !steps.length;
  }

  async function act(path, done) {
    try {
      const r = await api(path, {});
      if (done) done(r);
      render(path === 'quick/pairing' ? null : r);
    } catch (x) {
      notice(x.message, true);
    }
  }

  el('quick-start').onclick = () => act('quick/start');
  el('quick-stop').onclick = () => act('quick/stop');
  el('quick-revoke').onclick = () => act('quick/revoke', () => notice('ChatGPT and Claude were disconnected from HA.'));
  el('quick-copy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(el('quick-address').value);
      notice('Address copied.');
    } catch {
      el('quick-address').select();
    }
  };
  for (const b of [el('quick-manual-chatgpt'), el('quick-manual-claude')]) {
    b.onclick = () => {
      const name = b.dataset.manual;
      showSteps(name);
      const url = (providers[name] || {}).url;
      if (url) window.open(url, '_blank', 'noopener');
    };
  }
  for (const b of [el('quick-chatgpt'), el('quick-claude')]) {
    b.onclick = async () => {
      try {
        render(await api('quick/connect', {provider: b.dataset.provider}));
        notice('Connecting ' + b.dataset.provider + '. Progress shows under the buttons.');
      } catch (x) { notice(x.message, true); }
    };
  }
  el('quick-code-show').onclick = () => act('quick/pairing', r => {
    el('quick-code').hidden = false;
    el('quick-code').innerHTML = `Approval code: <b class="code"></b> (valid for 10 minutes, one use).`;
    el('quick-code').querySelector('b').textContent = r.code;
  });

  let stepsSet = false;
  function renderHelper(h) {
    if (!h) return;
    if (el('helper-folder').value !== h.folder) el('helper-folder').value = h.folder;
    el('helper-status').textContent = h.connected ? 'Installed and connected to HA.'
      : h.last_seen ? 'Installed. Last reached HA ' + ago(h.last_seen) + '. Open Chrome to reconnect.'
      : h.error ? 'Chrome can\'t reach HA yet: ' + h.error
      : 'Not installed yet, or Chrome is closed.';
    el('helper-card').classList.toggle('done', !!h.connected);
    // Once installed, the steps are only needed again after moving HA.
    if (!stepsSet) { el('helper-steps').open = !h.last_seen; stepsSet = true; }
  }
  el('helper-open-extensions').onclick = async () => {
    try { await navigator.clipboard.writeText('chrome://extensions'); } catch {}
    notice('Opening Chrome…');
    try {
      const r = await api('helper/open-extensions', {});
      if (r.typed) notice('Chrome\'s Extensions page is open in a new window. Next: turn on Developer mode (top right).');
      else if (r.opened) notice('Chrome opened, but HA couldn\'t type the address safely. It\'s copied: click Chrome\'s address bar, press Ctrl+V, then Enter.', true);
      else notice('HA couldn\'t find Chrome. The address is copied: open Chrome, press Ctrl+T, Ctrl+V, then Enter.', true);
    } catch (x) { notice(x.message, true); }
  };
  el('helper-copy-url').onclick = async () => {
    try { await navigator.clipboard.writeText('chrome://extensions'); notice('Copied. In Chrome: Ctrl+T, Ctrl+V, Enter.'); }
    catch { notice('Type chrome://extensions into a new Chrome tab\'s address bar.'); }
  };
  el('helper-copy').onclick = async () => {
    try { await navigator.clipboard.writeText(el('helper-folder').value); notice('Folder copied.'); }
    catch { el('helper-folder').select(); }
  };
  el('helper-open-folder').onclick = async () => {
    try {
      const r = await api('helper/open-folder', {});
      notice(r.opened ? 'Folder opened.' : 'Couldn\'t open the folder. Copy the path instead.', !r.opened);
    } catch (x) { notice(x.message, true); }
  };

  el('local-apps').onclick = async () => {
    try {
      const r = await api('mcp/local-apps', {});
      el('local-apps-result').replaceChildren(...r.apps.map(a => {
        const li = document.createElement('li');
        li.textContent = (a.app ? a.app + ': ' : '') + a.result;
        return li;
      }));
    } catch (x) {
      notice(x.message, true);
    }
  };

  async function poll() {
    try {
      const s = await api('status');
      render(s.quick_connect);
      renderHelper(s.chrome_helper);
    } catch {}
  }
  document.querySelector('[data-tab="settings"]').addEventListener('click', poll);
  setInterval(() => {
    if (el('connections').classList.contains('active')) poll();
  }, 3000);
  poll();
  window.renderQuickConnect = render;
})();

// Debugging uses its own endpoint, approvals and session-only tab grants.
(() => {
  const el = id => document.getElementById(id);
  let enabled = false, address = '';
  function renderDebug(state) {
    enabled = state.routes.length > 0;
    if (!el('debug-routes').children.length) {
      for (const route of state.available_routes) {
        const label = document.createElement('label');label.className = 'check';
        const input = document.createElement('input');input.type = 'checkbox';input.value = route;input.checked = !enabled || state.routes.includes(route);
        label.append(input, document.createTextNode(route));el('debug-routes').append(label);
      }
    }
    for (const input of el('debug-routes').querySelectorAll('input')) {
      input.disabled = enabled;
      if (enabled) input.checked = state.routes.includes(input.value);
    }
    if (address !== state.endpoint || !enabled) {el('debug-code').textContent = '';el('debug-code').hidden = true;}
    address = state.endpoint;el('debug-address').value = address;
    el('debug-stop').disabled = !enabled;
    el('debug-code-show').disabled = state.state !== 'ready';
    const progress = Object.entries(state.setup.progress || {}).map(([p,v]) => p+': '+v.message);
    const contacts = Object.entries(state.services || {}).filter(([,v])=>v.last_tool_at || v.tools_listed_at || v.authorized).map(([p,v]) => p+(v.last_tool_at ? ': debugging tool used.' : v.tools_listed_at ? ': debugging tools discovered.' : ': approved; waiting for contact.'));
    el('debug-status').textContent = [enabled ? state.message || 'Starting debugging…' : 'Debugging is off.',...progress,...contacts].join(' ');
  }
  async function refreshDebug() {try {renderDebug(await api('debug/status',{}));} catch(e) {notice(e.message,true);}}
  async function startDebug(provider) {
    try {
      const routes = [...el('debug-routes').querySelectorAll('input:checked')].map(e=>e.value);
      renderDebug(await api('debug/start',{routes}));
      if (provider) renderDebug(await api('debug/connect',{provider}));
    } catch(e) {notice(e.message,true);}
  }
  el('debug-chatgpt').onclick = ()=>startDebug('ChatGPT');
  el('debug-claude').onclick = ()=>startDebug('Claude');
  el('debug-start').onclick = ()=>startDebug();
  el('debug-stop').onclick = async()=>{try {renderDebug(await api('debug/stop',{}));}catch(e){notice(e.message,true);}};
  el('debug-copy').onclick = async()=>{try {await navigator.clipboard.writeText(address);notice('Debugging address copied.');}catch(e){notice(e.message,true);}};
  el('debug-code-show').onclick = async()=>{try {const result=await api('debug/pairing',{});el('debug-code').textContent=result.code;el('debug-code').hidden=false;}catch(e){notice(e.message,true);}};
  refreshDebug();
  setInterval(()=>{if(el('connections').classList.contains('active'))refreshDebug();},5000);
})();
