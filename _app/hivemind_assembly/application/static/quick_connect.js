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
    if (q.address_changed) text += ' The address changed, so connect ChatGPT and Claude again.';
    el('quick-status').textContent = text;
    el('quick-status').classList.toggle('warn-text', q.state === 'error');
    const d = q.download;
    el('quick-download').hidden = !d;
    if (d && d.total_bytes) el('quick-download-bar').value = Math.round(100 * d.done_bytes / d.total_bytes);
    el('quick-ready').hidden = q.state !== 'ready';
    if (el('quick-address').value !== q.endpoint) el('quick-address').value = q.endpoint || '';
    const services = q.services || {};
    el('quick-services').replaceChildren(...Object.keys(providers).map(name => {
      const li = document.createElement('li');
      li.textContent = serviceLine(name, services[name] || {});
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
