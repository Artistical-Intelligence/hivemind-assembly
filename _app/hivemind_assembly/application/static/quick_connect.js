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
    let text = q.message || 'Not started.';
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
      ? 'ChatGPT and Claude reach HA at a permanent address (' + q.permanent.origin + '). Keep HA running while you chat. Approvals are kept through restarts.'
      : temporaryIntro;
    el('quick-auto').hidden = permanent;
    el('quick-auto-progress').hidden = permanent;
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
  for (const b of [el('quick-chatgpt'), el('quick-claude')]) {
    b.onclick = () => {
      const name = b.dataset.provider;
      showSteps(name);
      const url = (providers[name] || {}).url;
      if (url) window.open(url, '_blank', 'noopener');
    };
  }
  el('quick-code-show').onclick = () => act('quick/pairing', r => {
    el('quick-code').hidden = false;
    el('quick-code').innerHTML = `Approval code: <b class="code"></b> (valid for 10 minutes, one use).`;
    el('quick-code').querySelector('b').textContent = r.code;
  });

  el('helper-install').onclick = async () => {
    try {
      const r = await api('helper/install', {open: true});
      el('helper-folder').value = r.folder;
      el('helper-steps').hidden = false;
      notice(r.opened ? 'Chrome\'s Extensions page is open. Follow the steps below.' : 'Open chrome://extensions in Chrome, then follow the steps below.');
    } catch (x) {
      notice(x.message, true);
    }
  };
  el('helper-copy').onclick = async () => {
    try {
      await navigator.clipboard.writeText(el('helper-folder').value);
      notice('Folder copied.');
    } catch {
      el('helper-folder').select();
    }
  };

  el('quick-auto').onsubmit = async e => {
    e.preventDefault();
    try {
      const chosen = [...e.target.elements.provider].filter(b => b.checked).map(b => b.value);
      renderAuto(await api('quick/auto', {providers: chosen}));
      notice(chosen.length ? 'HA will reconnect ' + chosen.join(' and ') + ' itself when the address changes.' : 'Automatic reconnect is off.');
    } catch (x) {
      notice(x.message, true);
    }
  };
  el('quick-reconnect').onclick = async () => {
    try {
      renderAuto(await api('quick/reconnect', {}));
      notice('Reconnecting in HA\'s assistant windows. Progress shows below.');
    } catch (x) {
      notice(x.message, true);
    }
  };

  el('permanent-setup').onsubmit = async e => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      notice('Setting up the permanent address. This takes about a minute.');
      render(await api('permanent/setup', {token: f.token.value, account_id: f.account_id.value, confirmed_free: f.confirmed_free.checked}));
      f.token.value = '';
      notice('Permanent address ready. Connect ChatGPT and Claude to it once.');
    } catch (x) {
      f.token.value = '';
      notice(x.message, true);
    }
  };
  el('permanent-off').onclick = async () => {
    try {
      render(await api('permanent/off', {}));
      notice('Using the temporary address again. The Worker stays in your Cloudflare account.');
    } catch (x) {
      notice(x.message, true);
    }
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
    } catch {}
  }
  document.querySelector('[data-tab="connections"]').addEventListener('click', poll);
  setInterval(() => {
    if (el('connections').classList.contains('active')) poll();
  }, 3000);
  poll();
  window.renderQuickConnect = render;
})();
