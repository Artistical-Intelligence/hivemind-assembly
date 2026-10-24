// AI assistants page: one card per assistant with plain setup steps and progress.
(() => {
  const el = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const ROLE = {adviser: 'Adviser', reviewer: 'Reviewer', worker: 'Worker'};
  const PROVIDER = {openai: 'ChatGPT', claude: 'Claude'};
  const STEPS = ['Open a tab', 'Sign in', 'Find the model and effort', 'Read usage', 'Test the conversation'];
  const STEP_OF = {opening: 0, authentication: 1, binding_required: 2, allowance_mapping: 3, waiting_quota: 3,
    ready_for_session: 4, bound: 4, waiting_delivery: 4, verified: 5};
  const CONTROL = {mode: 'mode picker', model: 'model picker', effort: 'effort picker', account: 'account name',
    composer: 'message box', send: 'send button', attachments: 'attach button'};

  const minutes = since => since ? Math.max(0, Math.round((Date.now() / 1000 - since) / 60)) : 0;
  const forHow = since => {
    const m = minutes(since);
    return m < 1 ? '' : m === 1 ? ' (for 1 min)' : ` (for ${m} min)`;
  };

  // What the assistant is doing, in plain words, and whether the owner needs to act.
  function describe(r) {
    const s = r.setup || {};
    const name = PROVIDER[r.provider] || r.provider;
    const stuck = minutes(s.since) >= 2;
    if (r.status.ready) return {text: 'Ready.', tone: 'ok', step: 5};
    if (r.out_of_usage) return {text: 'Out of usage on this account. HA checks again once a day and continues when it refills.', tone: 'warn', step: 3};
    switch (s.stage) {
      case 'opening':
        return {text: `Opening ${name} in a tab…`, step: 0};
      case 'authentication':
        return {
          text: /already open/.test(s.instruction || '')
            ? `Waiting for you to sign in to ${name} in the tab HA opened. One sign-in covers every ${name} assistant.`
            : `Sign in to ${name} in the tab HA opened (select Show tab). Setup continues by itself.`,
          tone: 'act', step: 1};
      case 'binding_required': {
        const missing = (s.instruction || '').split(':').pop().split(',').map(x => CONTROL[x.trim()] || x.trim()).filter(Boolean);
        return {
          text: stuck
            ? `HA can't find the ${missing.join(', ')} on the ${name} page. Check the picture of what HA sees; a pop-up or a changed page may be in the way.`
            : `Looking for the ${missing.join(', ') || 'controls'} on the ${name} page…`,
          tone: stuck ? 'warn' : '', step: 2};
      }
      case 'allowance_mapping':
        return {text: stuck ? `HA can't find ${name}'s usage page for this account.` : `Reading ${name} usage…`, tone: stuck ? 'warn' : '', step: 3};
      case 'waiting_quota':
        return {text: 'Waiting for this account to have enough usage left (at least 10%).', tone: 'warn', step: 3};
      case 'waiting_delivery':
        return {text: s.instruction || 'Retrying…', tone: 'act', step: 4};
      case 'ready_for_session':
      case 'bound':
        return {text: 'Found the controls. Starting this assistant\'s own conversation…', step: 4};
      case 'verified':
        return {text: 'Set up. Checking it is ready…', step: 5};
      case 'attention':
        return {text: s.instruction || 'Setup stopped.', tone: 'warn', step: null};
      default:
        return {text: 'Not set up yet.', step: null};
    }
  }

  function card(r) {
    const s = r.setup || {};
    const d = describe(r);
    const name = PROVIDER[r.provider] || r.provider;
    const working = s.running || ['opening', 'authentication', 'binding_required', 'allowance_mapping', 'waiting_delivery', 'ready_for_session', 'bound'].includes(s.stage);
    const step = d.step;
    const bar = step === null || r.status.ready ? '' :
      `<progress max="${STEPS.length}" value="${step}"></progress><p class="muted">Step ${Math.min(step + 1, STEPS.length)} of ${STEPS.length}: ${esc(STEPS[Math.min(step, STEPS.length - 1)])}${forHow(s.since)}</p>`;
    const show = s.tab_open
      ? `<button data-native-show="${esc(r.id)}">Show tab</button>`
      : `<button data-native-setup="${esc(r.id)}"${working ? ' disabled' : ''}>${r.status.ready ? 'Set up again' : 'Set up'}</button>`;
    const picture = s.snapshot ? `<button data-native-snapshot="${esc(r.id)}">What HA sees</button>` : '';
    return `<article class="assistant ${d.tone || ''}"><p class="role">${esc(ROLE[r.id.split('.')[0]] || r.id)} · ${esc(name)}</p>`
      + `<h2>${esc(r.model)} · ${esc(r.effort)}</h2><p class="assistant-status ${d.tone || ''}" role="status">${esc(d.text)}</p>${bar}`
      + `<div class="actions">${show}${picture}</div>`
      + `<details class="more"><summary>More</summary>`
      + `<p class="muted">${esc(r.mode)} surface · route ${esc(r.id)}</p>`
      + `<button data-probe="${esc(r.id)}">Check it works</button><span class="muted"> Reads the page to confirm the sign-in and controls. Sends nothing.</span><br>`
      + `<button data-native-renew="${esc(r.id)}">Start a new conversation</button><span class="muted"> Use when its conversation gets too long or confused.</span>`
      + `</details></article>`;
  }

  function render(s) {
    if (!s.routes) return;
    const list = el('route-list');
    const open = new Set([...list.querySelectorAll('details.more[open]')].map(x => x.closest('article')?.querySelector('[data-probe]')?.dataset.probe));
    list.innerHTML = s.routes.map(card).join('');
    list.querySelectorAll('details.more').forEach(x => { if (open.has(x.querySelector('[data-probe]')?.dataset.probe)) x.open = true; });
    const ready = s.routes.filter(r => r.status.ready).length;
    const busy = s.routes.some(r => r.setup?.running);
    el('assistants-overall').hidden = false;
    el('assistants-overall-bar').max = s.routes.length;
    el('assistants-overall-bar').value = ready;
    el('assistants-overall-text').textContent = `${ready} of ${s.routes.length} assistants ready` + (busy ? '. Setting up the others…' : '.');
    el('native-all').textContent = ready === s.routes.length ? 'Set up all again' : 'Set up all assistants';
  }

  document.addEventListener('click', async e => {
    const show = e.target.closest('[data-native-show]');
    const picture = e.target.closest('[data-native-snapshot]');
    try {
      if (show) {
        const r = await api('native/show', {route: show.dataset.nativeShow});
        notice(r.shown ? 'Switched to that tab in Chrome.' : 'That tab is closed. Select Set up to open it again.', !r.shown);
      }
      if (picture) {
        const r = await api('native/snapshot', {route: picture.dataset.nativeSnapshot});
        const view = el('snapshot-view');
        view.querySelector('img').src = 'data:image/jpeg;base64,' + r.jpeg;
        view.querySelector('p').textContent = 'What HA saw in this tab' + (r.taken ? ' at ' + new Date(r.taken * 1000).toLocaleTimeString() : '') + '.';
        view.showModal();
      }
    } catch (x) {
      notice(x.message, true);
    }
  });
  window.renderAssistants = render;
})();
